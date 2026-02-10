"""
SEO Analysis Endpoints for Siloq Backend

Provides:
- #15: Health Summary Endpoint - Comprehensive health check
- #16: Cannibalization Issues Endpoint - Keyword cannibalization analysis
- #17: Link Opportunities Endpoint - Find internal/external link opportunities
- #18: Contextual Spoke Generation - Generate content spokes from hub topics
- #19: Link Insertion Endpoint - Suggest and manage link insertions
"""
import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from django.db import connection
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404

from sites.models import Site
from seo.models import Page, SEOData
from integrations.models import Scan
from integrations.permissions import IsAPIKeyAuthenticated
from integrations.authentication import APIKeyAuthentication

logger = logging.getLogger(__name__)


# =============================================================================
# #15 - Health Summary Endpoint
# =============================================================================

@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def health_summary(request):
    """
    Get comprehensive health summary for the site.
    
    GET /api/v1/health/summary/
    Headers: Authorization: Bearer <api_key>
    
    Returns comprehensive health metrics including:
    - Database connectivity
    - Pages status
    - SEO scores distribution
    - Critical issues count
    - Overall health score
    """
    site = request.auth['site']
    
    # Check database connectivity
    db_healthy = True
    db_response_time_ms = 0
    try:
        import time
        start = time.time()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_response_time_ms = round((time.time() - start) * 1000, 2)
    except Exception as e:
        db_healthy = False
        logger.error(f"Database health check failed: {e}")
    
    # Get pages statistics
    pages_stats = Page.objects.filter(site=site).aggregate(
        total_pages=Count('id'),
        published_pages=Count('id', filter=Q(status='publish')),
        draft_pages=Count('id', filter=Q(status='draft')),
        with_seo_data=Count('seo_data')
    )
    
    # Get SEO data statistics
    seo_stats = SEOData.objects.filter(page__site=site).aggregate(
        total_scanned=Count('id'),
        avg_seo_score=Count('id'),  # Will calculate manually
        critical_issues=Count('id', filter=Q(seo_score__lt=50)),
        warning_issues=Count('id', filter=Q(seo_score__gte=50, seo_score__lt=70)),
        good_pages=Count('id', filter=Q(seo_score__gte=70))
    )
    
    # Calculate average SEO score
    seo_data_list = SEOData.objects.filter(page__site=site).values_list('seo_score', flat=True)
    avg_score = sum(seo_data_list) / len(seo_data_list) if seo_data_list else 0
    
    # Count total issues across all pages
    total_critical = 0
    total_warnings = 0
    for seo in SEOData.objects.filter(page__site=site):
        for issue in seo.issues:
            if issue.get('severity') == 'high':
                total_critical += 1
            elif issue.get('severity') == 'medium':
                total_warnings += 1
    
    # Calculate overall health score (0-100)
    # Based on: DB health (20%), pages with SEO data (20%), avg SEO score (40%), issues (20%)
    health_score = 100
    if not db_healthy:
        health_score -= 20
    
    if pages_stats['total_pages'] > 0:
        coverage = pages_stats['with_seo_data'] / pages_stats['total_pages']
        health_score -= (1 - coverage) * 20
    
    health_score = (health_score * 0.4) + (avg_score * 0.4)
    
    # Deduct for issues
    issue_penalty = min((total_critical * 5) + (total_warnings * 2), 20)
    health_score -= issue_penalty
    health_score = max(0, min(100, round(health_score)))
    
    # Determine health status
    if health_score >= 80:
        health_status = 'healthy'
    elif health_score >= 60:
        health_status = 'warning'
    else:
        health_status = 'critical'
    
    summary = {
        'status': health_status,
        'health_score': health_score,
        'timestamp': timezone.now().isoformat(),
        'database': {
            'healthy': db_healthy,
            'response_time_ms': db_response_time_ms
        },
        'pages': {
            'total': pages_stats['total_pages'],
            'published': pages_stats['published_pages'],
            'draft': pages_stats['draft_pages'],
            'with_seo_data': pages_stats['with_seo_data'],
            'coverage_percentage': round(
                (pages_stats['with_seo_data'] / pages_stats['total_pages'] * 100), 2
            ) if pages_stats['total_pages'] > 0 else 0
        },
        'seo_summary': {
            'average_score': round(avg_score, 1),
            'pages_scanned': seo_stats['total_scanned'],
            'critical_issues': total_critical,
            'warning_issues': total_warnings,
            'pages_by_score': {
                'critical': SEOData.objects.filter(page__site=site, seo_score__lt=50).count(),
                'warning': SEOData.objects.filter(page__site=site, seo_score__gte=50, seo_score__lt=70).count(),
                'good': SEOData.objects.filter(page__site=site, seo_score__gte=70, seo_score__lt=90).count(),
                'excellent': SEOData.objects.filter(page__site=site, seo_score__gte=90).count()
            }
        }
    }
    
    return Response(summary)


# =============================================================================
# #16 - Cannibalization Issues Endpoint
# =============================================================================

@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def cannibalization_issues(request):
    """
    Get detailed keyword cannibalization analysis.
    
    GET /api/v1/analysis/cannibalization/
    Headers: Authorization: Bearer <api_key>
    
    Query params:
    - min_conflicts: Minimum number of conflicts to report (default: 2)
    - severity: Filter by severity - 'high', 'medium', 'all' (default: 'all')
    
    Returns:
    - Pages competing for same keywords
    - Overlapping topics
    - Content similarity analysis
    - Recommendations for consolidation
    """
    site = request.auth['site']
    min_conflicts = int(request.GET.get('min_conflicts', 2))
    severity_filter = request.GET.get('severity', 'all')
    
    # Get all pages with SEO data
    pages_with_seo = SEOData.objects.filter(page__site=site).select_related('page')
    
    # Build keyword index - track which pages target which keywords
    keyword_index = defaultdict(list)
    
    for seo in pages_with_seo:
        # Extract keywords from various sources
        keywords = set()
        
        # From meta keywords
        if seo.meta_keywords:
            keywords.update([k.strip().lower() for k in seo.meta_keywords.split(',')])
        
        # From meta description (extract key terms)
        if seo.meta_description:
            desc_words = set(seo.meta_description.lower().split())
            # Filter for meaningful terms (longer than 4 chars)
            keywords.update([w for w in desc_words if len(w) > 4])
        
        # From H1 heading
        if seo.h1_text:
            keywords.add(seo.h1_text.lower())
        
        # From title
        if seo.page.title:
            title_words = set(seo.page.title.lower().split())
            keywords.update([w for w in title_words if len(w) > 4])
        
        # Add page to keyword index
        for keyword in keywords:
            if len(keyword) > 3:  # Filter out very short terms
                keyword_index[keyword].append({
                    'page_id': seo.page.id,
                    'page_url': seo.page.url,
                    'page_title': seo.page.title,
                    'seo_score': seo.seo_score
                })
    
    # Find cannibalization conflicts (multiple pages for same keyword)
    conflicts = []
    
    for keyword, pages in keyword_index.items():
        if len(pages) >= min_conflicts:
            # Sort by SEO score (highest first)
            pages_sorted = sorted(pages, key=lambda x: x['seo_score'], reverse=True)
            
            # Determine severity
            if len(pages) >= 4:
                severity = 'high'
            elif len(pages) >= 2:
                avg_score = sum(p['seo_score'] for p in pages) / len(pages)
                if avg_score < 50:
                    severity = 'high'
                elif avg_score < 70:
                    severity = 'medium'
                else:
                    severity = 'low'
            else:
                severity = 'low'
            
            # Apply severity filter
            if severity_filter != 'all' and severity != severity_filter:
                continue
            
            conflicts.append({
                'keyword': keyword,
                'conflict_count': len(pages),
                'severity': severity,
                'pages': pages_sorted,
                'primary_page': pages_sorted[0] if pages_sorted else None,
                'recommendation': _generate_cannibalization_recommendation(keyword, pages_sorted)
            })
    
    # Sort by severity and conflict count
    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    conflicts.sort(key=lambda x: (severity_order.get(x['severity'], 3), -x['conflict_count']))
    
    # Calculate summary statistics
    total_keywords_analyzed = len(keyword_index)
    conflicting_keywords = len([k for k, v in keyword_index.items() if len(v) >= min_conflicts])
    
    high_severity = len([c for c in conflicts if c['severity'] == 'high'])
    medium_severity = len([c for c in conflicts if c['severity'] == 'medium'])
    low_severity = len([c for c in conflicts if c['severity'] == 'low'])
    
    response_data = {
        'summary': {
            'total_keywords_analyzed': total_keywords_analyzed,
            'conflicting_keywords': conflicting_keywords,
            'conflict_rate': round((conflicting_keywords / total_keywords_analyzed * 100), 2) if total_keywords_analyzed > 0 else 0,
            'high_severity': high_severity,
            'medium_severity': medium_severity,
            'low_severity': low_severity
        },
        'conflicts': conflicts,
        'recommendations': {
            'consolidate_similar': [c for c in conflicts if c['severity'] == 'high'],
            'differentiate_content': [c for c in conflicts if c['severity'] == 'medium'],
            'merge_redundant': [c for c in conflicts if c['conflict_count'] >= 4]
        }
    }
    
    return Response(response_data)


def _generate_cannibalization_recommendation(keyword: str, pages: List[Dict]) -> str:
    """Generate a recommendation for resolving cannibalization."""
    if len(pages) >= 4:
        return f"Consider consolidating the {len(pages)} competing pages for '{keyword}' into one authoritative page."
    elif pages[0]['seo_score'] >= 70 and len(pages) == 2:
        return f"Keep '{pages[0]['page_title']}' as primary for '{keyword}', differentiate the other page's focus."
    else:
        return f"Review and differentiate content targeting '{keyword}' across these {len(pages)} pages."


# =============================================================================
# #17 - Link Opportunities Endpoint
# =============================================================================

@api_view(['GET'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def link_opportunities(request):
    """
    Find internal and external link opportunities.
    
    GET /api/v1/analysis/link-opportunities/
    Headers: Authorization: Bearer <api_key>
    
    Query params:
    - type: 'internal', 'external', 'broken', 'all' (default: 'all')
    - min_score: Minimum page SEO score to include (default: 0)
    
    Returns:
    - Internal linking suggestions (orphan pages, related content)
    - External link opportunities
    - Broken links to fix
    - Pages needing more internal links
    """
    site = request.auth['site']
    opp_type = request.GET.get('type', 'all')
    min_score = int(request.GET.get('min_score', 0))
    
    # Get all pages with SEO data for this site
    pages_with_seo = SEOData.objects.filter(
        page__site=site,
        seo_score__gte=min_score
    ).select_related('page')
    
    opportunities = {
        'internal': [],
        'external': [],
        'broken': [],
        'orphan_pages': []
    }
    
    # Build content index for finding related pages
    content_index = {}
    for seo in pages_with_seo:
        content_index[seo.page.id] = {
            'title': seo.page.title,
            'url': seo.page.url,
            'content': seo.page.content or '',
            'headings': [seo.h1_text] + seo.h2_texts + seo.h3_texts,
            'internal_links': seo.internal_links or [],
            'external_links': seo.external_links or []
        }
    
    # Find internal linking opportunities
    if opp_type in ['internal', 'all']:
        for seo in pages_with_seo:
            current_links = set(seo.internal_links or [])
            
            # Find pages that mention this page's topic but don't link to it
            for other_id, other_content in content_index.items():
                if other_id == seo.page.id:
                    continue
                
                # Check if other page mentions this page's topic
                page_title_lower = seo.page.title.lower()
                other_content_text = ' '.join([
                    other_content['title'],
                    other_content['content'][:500]  # First 500 chars
                ]).lower()
                
                if page_title_lower in other_content_text:
                    # Check if already linked
                    if seo.page.url not in other_content['internal_links']:
                        opportunities['internal'].append({
                            'source_page': {
                                'id': other_id,
                                'title': other_content['title'],
                                'url': other_content['url']
                            },
                            'target_page': {
                                'id': seo.page.id,
                                'title': seo.page.title,
                                'url': seo.page.url
                            },
                            'context': f"'{seo.page.title}' is mentioned in content",
                            'priority': 'high' if seo.seo_score >= 70 else 'medium'
                        })
    
    # Find orphan pages (pages with no internal links pointing to them)
    if opp_type in ['internal', 'all', 'orphan']:
        all_internal_links = set()
        for seo in pages_with_seo:
            all_internal_links.update(seo.internal_links or [])
        
        for seo in pages_with_seo:
            page_url = seo.page.url
            if page_url not in all_internal_links and seo.page.status == 'publish':
                opportunities['orphan_pages'].append({
                    'page_id': seo.page.id,
                    'title': seo.page.title,
                    'url': page_url,
                    'seo_score': seo.seo_score,
                    'recommendation': 'Add internal links from related pages'
                })
    
    # Find external link opportunities
    if opp_type in ['external', 'all']:
        # Pages with few external links but good content
        for seo in pages_with_seo:
            ext_count = seo.external_links_count or 0
            if ext_count < 2 and seo.word_count > 300:
                opportunities['external'].append({
                    'page_id': seo.page.id,
                    'title': seo.page.title,
                    'url': seo.page.url,
                    'current_external_links': ext_count,
                    'recommendation': 'Consider adding authoritative external references'
                })
    
    # Find potential broken links (basic check for common patterns)
    if opp_type in ['broken', 'all']:
        for seo in pages_with_seo:
            for link in (seo.internal_links or []):
                # Check if link points to a page that doesn't exist
                if not Page.objects.filter(site=site, url=link).exists():
                    if not link.startswith(('http://', 'https://', '#', 'mailto:')):
                        opportunities['broken'].append({
                            'source_page': {
                                'id': seo.page.id,
                                'title': seo.page.title,
                                'url': seo.page.url
                            },
                            'broken_link': link,
                            'type': 'internal',
                            'recommendation': 'Fix or remove broken internal link'
                        })
    
    # Calculate summary statistics
    summary = {
        'total_internal_opportunities': len(opportunities['internal']),
        'total_external_opportunities': len(opportunities['external']),
        'total_orphan_pages': len(opportunities['orphan_pages']),
        'potential_broken_links': len(opportunities['broken']),
        'pages_analyzed': pages_with_seo.count()
    }
    
    # Filter response based on type parameter
    if opp_type == 'internal':
        response_data = {
            'summary': summary,
            'internal_opportunities': opportunities['internal'][:50],
            'orphan_pages': opportunities['orphan_pages']
        }
    elif opp_type == 'external':
        response_data = {
            'summary': summary,
            'external_opportunities': opportunities['external'][:50]
        }
    elif opp_type == 'broken':
        response_data = {
            'summary': summary,
            'broken_links': opportunities['broken'][:50]
        }
    else:
        response_data = {
            'summary': summary,
            'internal_opportunities': opportunities['internal'][:30],
            'external_opportunities': opportunities['external'][:30],
            'orphan_pages': opportunities['orphan_pages'][:30],
            'broken_links': opportunities['broken'][:30]
        }
    
    return Response(response_data)


# =============================================================================
# #18 - Contextual Spoke Generation
# =============================================================================

@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def contextual_spoke_generation(request):
    """
    Generate contextual spoke content ideas from hub topics.
    
    POST /api/v1/analysis/spoke-generation/
    Headers: Authorization: Bearer <api_key>
    
    Body:
    {
        "hub_topic": "Main topic/pillar content",
        "num_spokes": 5,
        "target_keywords": ["keyword1", "keyword2"],
        "existing_content_ids": [1, 2, 3]  # Optional - page IDs to avoid duplication
    }
    
    Returns:
    - Generated spoke topics
    - Content angle suggestions
    - Internal linking recommendations
    - Content brief outlines
    """
    site = request.auth['site']
    
    hub_topic = request.data.get('hub_topic', '').strip()
    num_spokes = min(int(request.data.get('num_spokes', 5)), 10)
    target_keywords = request.data.get('target_keywords', [])
    existing_content_ids = request.data.get('existing_content_ids', [])
    
    if not hub_topic:
        return Response(
            {'error': 'hub_topic is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get existing content for this site
    existing_titles = set()
    if existing_content_ids:
        existing_pages = Page.objects.filter(
            site=site,
            id__in=existing_content_ids
        ).values_list('title', flat=True)
        existing_titles.update(existing_pages)
    
    # Get all existing titles to avoid duplication
    all_site_titles = set(Page.objects.filter(site=site).values_list('title', flat=True))
    
    # Generate spoke content ideas
    spokes = _generate_spoke_ideas(
        hub_topic=hub_topic,
        target_keywords=target_keywords,
        num_spokes=num_spokes,
        existing_titles=all_site_titles
    )
    
    # Find internal linking opportunities for each spoke
    for spoke in spokes:
        spoke['linking_opportunities'] = _find_spoke_linking_opportunities(
            site=site,
            spoke_topic=spoke['title'],
            hub_topic=hub_topic
        )
    
    response_data = {
        'hub_topic': hub_topic,
        'target_keywords': target_keywords,
        'spokes_generated': len(spokes),
        'spokes': spokes,
        'content_strategy': {
            'recommended_publish_schedule': '1-2 spokes per week',
            'internal_linking_priority': 'Link all spokes to hub, cross-link related spokes',
            'content_refresh_cycle': 'Review and update every 6 months'
        }
    }
    
    return Response(response_data)


def _generate_spoke_ideas(
    hub_topic: str,
    target_keywords: List[str],
    num_spokes: int,
    existing_titles: set
) -> List[Dict]:
    """Generate spoke content ideas based on the hub topic."""
    
    # Template patterns for generating spoke topics
    spoke_templates = [
        "What is {topic}? A Complete Guide",
        "{topic} vs [Alternative]: Which is Better?",
        "Top 10 {topic} Tools for 2025",
        "How to Get Started with {topic}",
        "{topic} Best Practices: Expert Tips",
        "Common {topic} Mistakes to Avoid",
        "{topic} Case Studies: Real Results",
        "{topic} Trends You Need to Know",
        "How to Measure {topic} Success",
        "{topic} for Beginners: Step-by-Step",
        "Advanced {topic} Strategies",
        "{topic} Checklist: Don't Miss These",
        "The Future of {topic} in 2025",
        "{topic} ROI: How to Calculate Returns",
        "{topic} Integration: What Works Best"
    ]
    
    import random
    random.seed(hash(hub_topic) % 10000)  # Seed for consistent results
    
    selected_templates = random.sample(spoke_templates, min(num_spokes, len(spoke_templates)))
    
    spokes = []
    for i, template in enumerate(selected_templates, 1):
        title = template.format(topic=hub_topic)
        
        # Skip if too similar to existing content
        if _is_title_similar(title, existing_titles):
            continue
        
        spoke = {
            'id': i,
            'title': title,
            'content_angle': _determine_content_angle(template),
            'target_word_count': _determine_word_count(template),
            'difficulty': _determine_difficulty(template),
            'priority_keywords': target_keywords[:2] if target_keywords else [hub_topic],
            'content_brief': {
                'sections': _generate_content_sections(title, hub_topic),
                'key_points': _generate_key_points(hub_topic),
                'call_to_action': f"Link back to main {hub_topic} pillar page"
            }
        }
        spokes.append(spoke)
    
    return spokes[:num_spokes]


def _is_title_similar(title: str, existing_titles: set) -> bool:
    """Check if a title is too similar to existing titles."""
    title_lower = title.lower()
    for existing in existing_titles:
        if title_lower in existing.lower() or existing.lower() in title_lower:
            return True
    return False


def _determine_content_angle(template: str) -> str:
    """Determine the content angle based on template type."""
    if 'vs' in template:
        return 'comparison'
    elif 'Top' in template:
        return 'listicle'
    elif 'How to' in template:
        return 'tutorial'
    elif 'Mistakes' in template:
        return 'educational_warning'
    elif 'Guide' in template:
        return 'comprehensive_guide'
    elif 'Trends' in template:
        return 'trend_analysis'
    else:
        return 'educational'


def _determine_word_count(template: str) -> int:
    """Determine recommended word count based on content type."""
    if 'Guide' in template or 'Complete' in template:
        return 2500
    elif 'vs' in template:
        return 1500
    elif 'Top' in template:
        return 2000
    elif 'Checklist' in template:
        return 1000
    else:
        return 1500


def _determine_difficulty(template: str) -> str:
    """Determine content creation difficulty."""
    if 'Advanced' in template or 'vs' in template:
        return 'hard'
    elif 'Beginners' in template or 'Mistakes' in template:
        return 'easy'
    else:
        return 'medium'


def _generate_content_sections(title: str, hub_topic: str) -> List[str]:
    """Generate recommended content sections."""
    return [
        f"Introduction to {hub_topic}",
        "Why This Matters",
        "Main Content Sections (3-5 subsections)",
        "Practical Examples",
        f"How This Connects to {hub_topic}",
        "Conclusion",
        f"Related: Link to main {hub_topic} guide"
    ]


def _generate_key_points(hub_topic: str) -> List[str]:
    """Generate key points to cover."""
    return [
        f"Define {hub_topic} in context",
        "Provide actionable advice",
        "Include real examples or data",
        "Address common questions",
        "Link to hub content naturally"
    ]


def _find_spoke_linking_opportunities(site, spoke_topic: str, hub_topic: str) -> List[Dict]:
    """Find pages that could link to this spoke content."""
    opportunities = []
    
    # Find pages that mention the spoke topic
    pages = Page.objects.filter(
        site=site,
        status='publish'
    ).select_related('seo_data')
    
    spoke_keywords = set(spoke_topic.lower().split())
    
    for page in pages:
        if not hasattr(page, 'seo_data'):
            continue
        
        content = (page.content or '').lower()
        title = (page.title or '').lower()
        
        # Check for keyword overlap
        title_words = set(title.split())
        overlap = spoke_keywords & title_words
        
        if len(overlap) >= 2:
            opportunities.append({
                'page_id': page.id,
                'page_title': page.title,
                'page_url': page.url,
                'context': f"Mentions: {', '.join(overlap)}",
                'suggested_anchor': spoke_topic.split(':')[0] if ':' in spoke_topic else spoke_topic
            })
    
    return opportunities[:5]  # Return top 5 opportunities


# =============================================================================
# #19 - Link Insertion Endpoint
# =============================================================================

@api_view(['GET', 'POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def link_insertion(request):
    """
    Suggest and manage link insertions in content.
    
    GET /api/v1/analysis/link-insertion/
    Get link insertion suggestions for a page
    
    Query params:
    - page_id: Target page ID
    - target_url: URL to insert links to
    
    POST /api/v1/analysis/link-insertion/
    Create a link insertion task or mark suggestion as applied
    
    Body:
    {
        "action": "suggest" | "apply" | "reject",
        "page_id": 123,
        "target_url": "https://...",
        "anchor_text": "suggested anchor",
        "position": "paragraph number or selector"
    }
    
    Returns:
    - Suggested insertion points
    - Anchor text recommendations
    - Context analysis
    """
    site = request.auth['site']
    
    if request.method == 'GET':
        return _get_link_suggestions(site, request)
    else:
        return _handle_link_insertion_action(site, request)


def _get_link_suggestions(site, request):
    """Get link insertion suggestions for a page."""
    page_id = request.GET.get('page_id')
    target_url = request.GET.get('target_url')
    
    if not page_id:
        return Response(
            {'error': 'page_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        page = Page.objects.get(site=site, id=page_id)
    except Page.DoesNotExist:
        return Response(
            {'error': 'Page not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Get page's SEO data
    try:
        seo = SEOData.objects.get(page=page)
    except SEOData.DoesNotExist:
        seo = None
    
    suggestions = {
        'page': {
            'id': page.id,
            'title': page.title,
            'url': page.url
        },
        'current_links': {
            'internal_count': seo.internal_links_count if seo else 0,
            'external_count': seo.external_links_count if seo else 0,
            'internal_urls': seo.internal_links if seo else [],
            'external_urls': seo.external_links if seo else []
        },
        'insertion_opportunities': []
    }
    
    # Find potential link opportunities
    if target_url:
        target_page = Page.objects.filter(site=site, url=target_url).first()
        if target_page:
            suggestions['target_page'] = {
                'id': target_page.id,
                'title': target_page.title,
                'url': target_page.url
            }
            
            # Analyze content for insertion points
            content = page.content or ''
            opportunities = _analyze_content_for_link_insertion(
                content=content,
                target_page=target_page,
                current_links=seo.internal_links if seo else []
            )
            suggestions['insertion_opportunities'] = opportunities
    else:
        # Suggest general internal linking opportunities
        opportunities = _find_general_link_opportunities(site, page)
        suggestions['insertion_opportunities'] = opportunities
    
    # Calculate link health metrics
    suggestions['link_health'] = {
        'internal_link_density': _calculate_link_density(seo.internal_links_count if seo else 0, seo.word_count if seo else 0),
        'external_link_density': _calculate_link_density(seo.external_links_count if seo else 0, seo.word_count if seo else 0),
        'recommended_internal_links': max(3, (seo.word_count // 500) if seo else 3),
        'link_gaps': _calculate_link_gaps(seo)
    }
    
    return Response(suggestions)


def _handle_link_insertion_action(site, request):
    """Handle POST actions for link insertion."""
    action = request.data.get('action')
    page_id = request.data.get('page_id')
    
    if not page_id:
        return Response(
            {'error': 'page_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        page = Page.objects.get(site=site, id=page_id)
    except Page.DoesNotExist:
        return Response(
            {'error': 'Page not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    if action == 'suggest':
        # Generate new suggestions
        target_url = request.data.get('target_url')
        return _get_link_suggestions(site, type('Request', (), {
            'GET': {'page_id': page_id, 'target_url': target_url}
        })())
    
    elif action == 'apply':
        # Mark a suggestion as applied (in a real system, this would update the content)
        return Response({
            'status': 'applied',
            'message': 'Link insertion suggestion marked as applied',
            'page_id': page_id,
            'target_url': request.data.get('target_url'),
            'anchor_text': request.data.get('anchor_text')
        })
    
    elif action == 'reject':
        # Mark suggestion as rejected
        return Response({
            'status': 'rejected',
            'message': 'Link insertion suggestion rejected',
            'page_id': page_id
        })
    
    else:
        return Response(
            {'error': f'Unknown action: {action}. Use suggest, apply, or reject'},
            status=status.HTTP_400_BAD_REQUEST
        )


def _analyze_content_for_link_insertion(content: str, target_page, current_links: List[str]) -> List[Dict]:
    """Analyze content and find insertion points for a link."""
    opportunities = []
    
    # Simple paragraph splitting
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    
    target_title_lower = target_page.title.lower()
    target_keywords = set(target_title_lower.split())
    
    for i, paragraph in enumerate(paragraphs, 1):
        para_lower = paragraph.lower()
        
        # Check if paragraph mentions target topic
        overlap = target_keywords & set(para_lower.split())
        
        if len(overlap) >= 2:
            # Check if not already linked
            already_linked = any(target_page.url in link for link in current_links)
            
            if not already_linked:
                # Generate anchor text suggestion
                anchor_suggestions = _generate_anchor_suggestions(paragraph, target_page.title)
                
                opportunities.append({
                    'position': i,
                    'paragraph_preview': paragraph[:150] + '...' if len(paragraph) > 150 else paragraph,
                    'anchor_text_suggestions': anchor_suggestions,
                    'context_match_score': min(100, len(overlap) * 20),
                    'priority': 'high' if len(overlap) >= 4 else 'medium',
                    'insertion_point': f'After sentence mentioning {list(overlap)[0]}'
                })
    
    return sorted(opportunities, key=lambda x: x['context_match_score'], reverse=True)[:10]


def _generate_anchor_suggestions(paragraph: str, target_title: str) -> List[str]:
    """Generate anchor text suggestions based on paragraph context."""
    suggestions = []
    
    # Extract key phrase from target title
    title_parts = target_title.split(':')[0] if ':' in target_title else target_title
    suggestions.append(title_parts)
    
    # Add variations
    if 'guide' not in title_parts.lower():
        suggestions.append(f"{title_parts} guide")
    if 'how to' not in title_parts.lower():
        suggestions.append(f"how to {title_parts.split()[0].lower()}")
    
    return suggestions[:3]


def _find_general_link_opportunities(site, page) -> List[Dict]:
    """Find general internal linking opportunities."""
    opportunities = []
    
    # Find related pages that should link to this page
    content = (page.content or '').lower()
    keywords = set(content.split())
    
    # Get other pages on the site
    other_pages = Page.objects.filter(
        site=site,
        status='publish'
    ).exclude(id=page.id)[:20]
    
    for other in other_pages:
        other_content = (other.content or '').lower()
        other_title = (other.title or '').lower()
        
        # Check for keyword overlap
        other_words = set(other_title.split()) | set(other_content.split()[:100])
        overlap = keywords & other_words
        
        if len(overlap) >= 3:
            opportunities.append({
                'source_page': {
                    'id': other.id,
                    'title': other.title,
                    'url': other.url
                },
                'reason': f"Content overlap: {len(overlap)} shared terms",
                'suggested_anchor': page.title,
                'priority': 'medium'
            })
    
    return opportunities[:10]


def _calculate_link_density(link_count: int, word_count: int) -> float:
    """Calculate link density (links per 1000 words)."""
    if word_count == 0:
        return 0.0
    return round((link_count / word_count) * 1000, 2)


def _calculate_link_gaps(seo) -> List[str]:
    """Calculate gaps in linking strategy."""
    gaps = []
    
    if not seo:
        return ['No SEO data available']
    
    if seo.internal_links_count == 0:
        gaps.append('No internal links - add at least 3 internal links')
    elif seo.internal_links_count < 3:
        gaps.append(f'Only {seo.internal_links_count} internal links - aim for 3-5')
    
    if seo.external_links_count == 0 and seo.word_count > 500:
        gaps.append('Consider adding 1-2 authoritative external references')
    
    if seo.images_without_alt > 0:
        gaps.append(f'{seo.images_without_alt} images missing alt text')
    
    return gaps


# Import timezone at module level
from django.utils import timezone
