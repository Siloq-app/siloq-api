"""
Content Recommendations API for Content Hub.

Analyzes site structure and suggests content to create based on:
- Silo gaps (money pages with few supporting articles)
- Service coverage (primary services without dedicated pages)
- Industry best practices (common content types for business type)
"""
import io
import os
import re
import base64
import uuid
import hashlib
import logging
from typing import List, Dict, Any

from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import Page
from seo.content_generation import generate_supporting_content
from seo.preflight_validation import run_preflight_validation
from ai.image_generator import generate_content_image

logger = logging.getLogger(__name__)


def _parse_city_page_doc(raw_text: str) -> dict:
    """
    Parse The Remodel Co's city page document format.
    
    Extracts structured data from 3-section format:
    1. Backend & Meta Data — slug, meta_title, meta_description
    2. On-Page Content — HTML-formatted content with special markers
    3. Developer Directions — ignored
    
    Returns dict with: slug, meta_title, meta_description, content_html, image_alts
    """
    result = {
        'slug': '',
        'meta_title': '',
        'meta_description': '',
        'content_html': '',
        'image_alts': [],
    }
    
    lines = raw_text.split('\n')
    current_section = None
    content_lines = []
    in_ul = False
    in_faq = False
    
    for line in lines:
        stripped = line.strip()
        
        # Section detection
        if 'Backend & Meta Data' in line or 'Backend and Meta Data' in line:
            current_section = 'meta'
            continue
        elif 'On-Page Content' in line or 'Copy & Paste' in line:
            current_section = 'content'
            continue
        elif 'Developer Directions' in line or 'Technical Implementation' in line:
            current_section = 'dev'
            break  # Stop parsing at dev section
        
        # ══════════════════════════════════════════════════════
        # Section 1: Backend & Meta Data
        # ══════════════════════════════════════════════════════
        if current_section == 'meta':
            if stripped.startswith('Slug:'):
                result['slug'] = stripped.replace('Slug:', '').strip().strip('/')
            elif stripped.startswith('Meta Title:'):
                result['meta_title'] = stripped.replace('Meta Title:', '').strip()
            elif stripped.startswith('Meta Description:'):
                # Meta description might span multiple lines
                desc = stripped.replace('Meta Description:', '').strip()
                result['meta_description'] = desc
        
        # ══════════════════════════════════════════════════════
        # Section 2: On-Page Content (Copy & Paste)
        # ══════════════════════════════════════════════════════
        elif current_section == 'content':
            if not stripped:
                # Close open lists
                if in_ul:
                    content_lines.append('</ul>')
                    in_ul = False
                content_lines.append('')
                continue
            
            # [H1] heading
            if stripped.startswith('[H1]'):
                text = stripped.replace('[H1]', '').strip()
                content_lines.append(f'<h1>{text}</h1>')
            
            # [H2] heading
            elif stripped.startswith('[H2]'):
                if in_ul:
                    content_lines.append('</ul>')
                    in_ul = False
                text = stripped.replace('[H2]', '').strip()
                content_lines.append(f'<h2>{text}</h2>')
            
            # [H3] heading
            elif stripped.startswith('[H3]'):
                if in_ul:
                    content_lines.append('</ul>')
                    in_ul = False
                text = stripped.replace('[H3]', '').strip()
                content_lines.append(f'<h3>{text}</h3>')
            
            # [Intro] paragraph
            elif stripped.startswith('[Intro]'):
                text = stripped.replace('[Intro]', '').strip()
                content_lines.append(f'<p class="intro">{text}</p>')
            
            # Q: question (FAQ)
            elif stripped.startswith('Q:'):
                if in_ul:
                    content_lines.append('</ul>')
                    in_ul = False
                if in_faq:
                    content_lines.append('</div>')
                question = stripped.replace('Q:', '').strip()
                content_lines.append(f'<div class="faq-item"><h3>{question}</h3>')
                in_faq = True
            
            # A: answer (FAQ)
            elif stripped.startswith('A:'):
                answer = stripped.replace('A:', '').strip()
                content_lines.append(f'<p>{answer}</p></div>')
                in_faq = False
            
            # Bullet points (lines starting with • or - or word:)
            elif stripped.startswith('•') or stripped.startswith('-') or re.match(r'^[A-Z][a-z]+:', stripped):
                if not in_ul:
                    content_lines.append('<ul>')
                    in_ul = True
                text = re.sub(r'^[•\-]\s*', '', stripped)
                content_lines.append(f'  <li>{text}</li>')
            
            # Links: [Link: /path/] anchor text or Link: *text [Link: /path/] more text*
            elif '[Link:' in stripped or 'Link:' in stripped:
                # Pattern: Link: *text [Link: /path/] more text.*
                # Or: [Link: /path/] anchor text
                processed = stripped
                
                # Replace [Link: /path/] anchor → <a href="/path/">anchor</a>
                processed = re.sub(
                    r'\[Link:\s*([^\]]+)\]\s*([^[*\n]+)',
                    r'<a href="\1">\2</a>',
                    processed
                )
                
                # Clean up any remaining markers
                processed = processed.replace('Link:', '').replace('*', '').strip()
                content_lines.append(f'<p>{processed}</p>')
            
            # Regular paragraph
            else:
                # Don't wrap if already in a list
                if in_ul:
                    content_lines.append(f'  <li>{stripped}</li>')
                else:
                    content_lines.append(f'<p>{stripped}</p>')
    
    # Close any open tags
    if in_ul:
        content_lines.append('</ul>')
    if in_faq:
        content_lines.append('</div>')
    
    result['content_html'] = '\n'.join(content_lines)
    
    return result


def _check_content_cannibalization(site, title: str, topic: str) -> dict:
    """
    Preflight check: will this content cannibalize existing pages?
    
    Checks:
    1. Exact/near-exact title match
    2. Slug collision
    3. Keyword overlap with existing pages (>60% shared keywords)
    
    Returns:
        {blocked: bool, conflicts: [...], suggestion: str}
    """
    from sites.analysis import extract_url_keywords
    from urllib.parse import urlparse
    import re
    
    # =========================================================================
    # Registry gate: check the Keyword Assignment Registry first
    # =========================================================================
    from seo.keyword_registry import check_keyword_available, get_keyword_owner

    for kw_candidate in [title.lower().strip(), topic.lower().strip()]:
        if not check_keyword_available(site, kw_candidate):
            owner = get_keyword_owner(site, kw_candidate)
            if owner:
                return {
                    'blocked': True,
                    'conflicts': [{
                        'page_id': owner.page_id,
                        'page_title': owner.page.title,
                        'page_url': owner.page.url,
                        'overlap_ratio': 1.0,
                        'shared_keywords': [kw_candidate],
                        'slug_collision': False,
                        'severity': 'high',
                        'registry_match': True,
                    }],
                    'suggestion': (
                        f'Keyword "{kw_candidate}" is already assigned to '
                        f'"{owner.page.title}" ({owner.page.url}) in the keyword registry. '
                        f'Choose a different keyword or reassign via the registry.'
                    ),
                }

    existing_pages = Page.objects.filter(
        site=site, status='publish', is_noindex=False
    ).values_list('id', 'title', 'url', 'post_type')
    
    title_lower = title.lower().strip()
    topic_lower = topic.lower().strip()
    
    # Extract keywords from the proposed title
    title_words = set(re.findall(r'[a-z]+', title_lower)) - {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
        'how', 'what', 'why', 'when', 'where', 'which', 'who',
        'and', 'or', 'not', 'but', 'if', 'then', 'your', 'you',
        'do', 'does', 'did', 'can', 'will', 'should', 'would', 'could',
    }
    
    if len(title_words) < 2:
        return {'blocked': False, 'conflicts': []}
    
    # Generate proposed slug
    proposed_slug = re.sub(r'[^a-z0-9-]', '', title_lower.replace(' ', '-'))
    
    conflicts = []
    
    for page_id, page_title, page_url, post_type in existing_pages:
        if not page_title:
            continue
        
        existing_title_lower = page_title.lower().strip()
        
        # Check 1: Near-exact title match (>90% word overlap)
        existing_words = set(re.findall(r'[a-z]+', existing_title_lower)) - {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'how', 'what', 'why', 'when', 'where', 'which', 'who',
            'and', 'or', 'not', 'but', 'if', 'then', 'your', 'you',
            'do', 'does', 'did', 'can', 'will', 'should', 'would', 'could',
        }
        
        if len(existing_words) < 2:
            continue
        
        overlap = title_words & existing_words
        union = title_words | existing_words
        overlap_ratio = len(overlap) / len(union) if union else 0
        
        # Check 2: Slug collision
        existing_slug = urlparse(page_url or '').path.rstrip('/').split('/')[-1] if page_url else ''
        slug_match = proposed_slug and existing_slug and (
            proposed_slug == existing_slug or
            proposed_slug in existing_slug or
            existing_slug in proposed_slug
        )
        
        if overlap_ratio >= 0.7 or slug_match:
            severity = 'high' if overlap_ratio >= 0.85 or slug_match else 'medium'
            conflicts.append({
                'page_id': page_id,
                'page_title': page_title,
                'page_url': page_url,
                'overlap_ratio': round(overlap_ratio, 2),
                'shared_keywords': list(overlap)[:10],
                'slug_collision': slug_match,
                'severity': severity,
            })
    
    if not conflicts:
        return {'blocked': False, 'conflicts': []}
    
    # Block if any high severity conflict
    has_high = any(c['severity'] == 'high' for c in conflicts)
    
    if has_high:
        top_conflict = conflicts[0]
        return {
            'blocked': True,
            'conflicts': conflicts,
            'suggestion': (
                f"This content would compete with '{top_conflict['page_title']}' "
                f"({top_conflict['page_url']}). Consider a different angle, "
                f"more specific topic, or merge into the existing page."
            ),
        }
    
    # Medium conflicts = warn but don't block
    return {
        'blocked': False,
        'conflicts': conflicts,
        'warning': 'Potential keyword overlap detected with existing pages. Review before publishing.',
    }


# Industry-standard content types by business type
INDUSTRY_CONTENT_TEMPLATES = {
    'local_service': [
        'FAQ: Common Questions About {service}',
        'How Much Does {service} Cost?',
        '{service} vs {alternative}: What\'s the Difference?',
        'DIY vs Professional {service}: Which is Right for You?',
        'How to Choose the Best {service} Provider',
        'Emergency {service}: What to Do',
        '{service} Checklist: What to Expect',
    ],
    'ecommerce': [
        'How to Choose the Right {product}',
        '{product} Buying Guide',
        'Top {number} {product} for {use_case}',
        '{product} Care and Maintenance Tips',
        '{product} Comparison Guide',
        'FAQ: Everything About {product}',
    ],
    'saas': [
        'Getting Started with {product}',
        '{product} vs {competitor}',
        'How to {solve_problem} with {product}',
        '{product} Pricing Guide',
        'Best Practices for {use_case}',
        '{product} FAQ',
    ],
    'content_blog': [
        'Ultimate Guide to {topic}',
        '{topic}: Everything You Need to Know',
        'Common Mistakes in {topic}',
        'How to Get Started with {topic}',
        '{topic} FAQ',
    ],
}


def _generate_rec_id(site_id: int, title: str) -> str:
    """Generate a stable recommendation ID based on site + title."""
    hash_input = f"{site_id}:{title}".encode('utf-8')
    hash_hex = hashlib.md5(hash_input).hexdigest()[:12]
    return f"rec_{hash_hex}"


def _analyze_silo_gaps(site: Site) -> List[Dict[str, Any]]:
    """
    Find money pages with few supporting pages and suggest topics.
    Returns list of recommendation dicts.
    """
    recommendations = []
    
    # Get all money pages (excluding homepage — homepage is never a content silo)
    money_pages = Page.objects.filter(
        site=site,
        is_money_page=True,
        status='publish'
    ).prefetch_related('supporting_pages')
    
    for money_page in money_pages:
        # Skip homepage — it's a brand page, not a service silo
        url_path = (money_page.url or '').rstrip('/')
        if url_path == '' or url_path.endswith('.com') or url_path.endswith('.com/'):
            continue
        page_slug = url_path.split('/')[-1] if '/' in url_path else ''
        if page_slug in ('', 'home', 'index', 'home-new', 'homepage'):
            continue
        
        # Skip pages with generic/uninformative titles
        title_lower = money_page.title.lower().strip()
        if title_lower in ('home', 'home new', 'homepage', 'main', 'index', ''):
            continue
        
        supporting_count = money_page.supporting_pages.filter(status='publish').count()
        
        # Determine priority
        if supporting_count == 0:
            priority = 'high'
            reason = f'No supporting content for "{money_page.title}" yet'
        elif supporting_count == 1:
            priority = 'high'
            reason = f'Only 1 supporting page for "{money_page.title}" — add more depth'
        elif supporting_count <= 3:
            priority = 'medium'
            reason = f'Only {supporting_count} supporting pages for "{money_page.title}"'
        else:
            continue
        
        # Use the full page title as the topic (it's already descriptive)
        # e.g., "Basement Remodeling", "Kitchen Remodeling"
        service_name = money_page.title.strip()
        
        # Generate topic-specific suggestions using the actual service name
        topic_suggestions = [
            f"Common Questions About {service_name}",
            f"How Much Does {service_name} Cost?",
            f"Signs You Need {service_name}",
        ]
        
        for idx, suggested_title in enumerate(topic_suggestions[:2]):
            rec_id = _generate_rec_id(site.id, suggested_title)
            recommendations.append({
                'id': rec_id,
                'title': suggested_title,
                'silo': service_name,
                'silo_id': money_page.id,
                'reason': reason,
                'priority': priority,
                'content_type': 'supporting_article',
                'estimated_searches': None,
            })
    
    return recommendations


def _analyze_service_coverage(site: Site) -> List[Dict[str, Any]]:
    """
    Check which primary services don't have dedicated pages.
    Returns list of recommendation dicts.
    """
    recommendations = []
    
    if not site.primary_services:
        return recommendations
    
    # Get existing page titles
    existing_pages = Page.objects.filter(site=site, status='publish')
    existing_titles = [p.title.lower() for p in existing_pages]
    existing_content = ' '.join(existing_titles)
    
    for service in site.primary_services:
        service_lower = service.lower()
        
        # Simple check: is this service mentioned in any page title?
        # This is a basic heuristic - could be improved with embeddings/semantic search
        if service_lower not in existing_content:
            rec_id = _generate_rec_id(site.id, f"Service: {service}")
            recommendations.append({
                'id': rec_id,
                'title': f"{service} - Complete Guide",
                'silo': None,
                'silo_id': None,
                'reason': f'No page found covering "{service}" (one of your primary services)',
                'priority': 'high',
                'content_type': 'money_page',
                'estimated_searches': None,
            })
    
    return recommendations


def _suggest_industry_content(site: Site) -> List[Dict[str, Any]]:
    """
    Suggest industry-standard content types based on business type.
    Returns list of recommendation dicts.
    """
    recommendations = []
    
    if not site.business_type or site.business_type == 'other':
        return recommendations
    
    templates = INDUSTRY_CONTENT_TEMPLATES.get(site.business_type, [])
    
    # Get existing page titles to avoid duplicates
    existing_pages = Page.objects.filter(site=site, status='publish')
    existing_titles = [p.title.lower() for p in existing_pages]
    
    # Fill in templates with service/product info
    services = site.primary_services[:3] if site.primary_services else ['your services']
    
    for template in templates[:4]:  # Limit to 4 suggestions
        # Fill in template with first service
        if services and services[0] != 'your services':
            suggested_title = template.format(
                service=services[0],
                product=services[0],
                alternative='alternatives',
                number='5',
                use_case='your needs',
                solve_problem='solve common problems',
                competitor='competitors',
                topic=services[0],
            )
        else:
            # Skip if no specific service to fill in
            continue
        
        # Check if similar content already exists (basic keyword match)
        if any(keyword in ' '.join(existing_titles) for keyword in suggested_title.lower().split()[:3]):
            continue
        
        rec_id = _generate_rec_id(site.id, f"Industry: {suggested_title}")
        recommendations.append({
            'id': rec_id,
            'title': suggested_title,
            'silo': None,
            'silo_id': None,
            'reason': f'Industry best practice content for {site.business_type} businesses',
            'priority': 'medium',
            'content_type': 'supporting_article',
            'estimated_searches': None,
        })
    
    return recommendations


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_content_recommendations(request, site_id):
    """
    GET /api/v1/sites/{site_id}/content-recommendations/
    
    Returns prioritized list of recommended content to create.
    
    Query params:
    - limit: Max number of recommendations (default: 10)
    - priority: Filter by priority (high/medium/low)
    """
    # Get site and verify ownership
    site = get_object_or_404(Site, id=site_id)
    
    if site.user != request.user:
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Collect recommendations from different sources
    recommendations = []
    
    # 1. Silo gap analysis (high priority)
    recommendations.extend(_analyze_silo_gaps(site))
    
    # 2. Service coverage analysis (high priority)
    recommendations.extend(_analyze_service_coverage(site))
    
    # 3. Industry-standard content (medium priority)
    recommendations.extend(_suggest_industry_content(site))
    
    # 4. Fallback: if no recommendations yet, generate from existing pages
    if not recommendations:
        recommendations.extend(_fallback_recommendations(site))
    
    # Sort by priority
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    recommendations.sort(key=lambda x: priority_order.get(x['priority'], 3))
    
    # Apply filters
    priority_filter = request.query_params.get('priority')
    if priority_filter:
        recommendations = [r for r in recommendations if r['priority'] == priority_filter]
    
    limit = int(request.query_params.get('limit', 10))
    recommendations = recommendations[:limit]
    
    return Response({
        'recommendations': recommendations,
        'total': len(recommendations),
        'site_id': site.id,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_from_recommendation(request, site_id, rec_id):
    """
    POST /api/v1/sites/{site_id}/content-recommendations/{rec_id}/generate/
    
    Generate content for a specific recommendation using OpenAI.
    
    Body (optional):
    - custom_title: Override the suggested title
    - custom_topic: Additional context for generation
    """
    # Get site and verify ownership
    site = get_object_or_404(Site, id=site_id)
    
    if site.user != request.user:
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Get all recommendations to find this one
    logger.info(f"Generate content request for site {site_id}, rec {rec_id}")
    all_recommendations = []
    all_recommendations.extend(_analyze_silo_gaps(site))
    all_recommendations.extend(_analyze_service_coverage(site))
    all_recommendations.extend(_suggest_industry_content(site))
    all_recommendations.extend(_fallback_recommendations(site))
    
    logger.info(f"Found {len(all_recommendations)} total recommendations, looking for rec_id={rec_id}")
    logger.info(f"Available rec IDs: {[r['id'] for r in all_recommendations[:10]]}")
    
    recommendation = next((r for r in all_recommendations if r['id'] == rec_id), None)
    
    if not recommendation:
        logger.warning(f"Recommendation {rec_id} not found among {len(all_recommendations)} recs")
        return Response(
            {'error': f'Recommendation not found. Available: {len(all_recommendations)} recs. This can happen if site data changed since the page loaded. Try refreshing.'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Get custom overrides
    custom_title = request.data.get('custom_title')
    custom_topic = request.data.get('custom_topic')
    include_image = request.data.get('include_image', True)
    
    title = custom_title or recommendation['title']
    topic = custom_topic or recommendation['title']
    
    # =========================================================================
    # PREFLIGHT: 9-check validation pipeline before generating content
    # Prevents keyword cannibalization, duplicate content, and silo violations
    # =========================================================================
    proposed_keyword = request.data.get('keyword', topic)
    proposed_slug = request.data.get('slug')
    proposed_h1 = request.data.get('h1', title)
    silo_id = recommendation.get('silo_id')
    page_type = recommendation.get('content_type', 'spoke')

    preflight = run_preflight_validation(
        site=site,
        proposed_title=title,
        proposed_keyword=proposed_keyword,
        proposed_slug=proposed_slug,
        proposed_h1=proposed_h1,
        silo_id=silo_id,
        page_type=page_type,
    )

    if preflight['status'] == 'block':
        return Response({
            'error': 'Content blocked by preflight validation',
            'blocking_check': preflight['blocking_check'],
            'checks': preflight['checks'],
            'warnings': preflight['warnings'],
            'suggestion': 'Differentiate the title, keyword, or angle to avoid cannibalization.',
        }, status=status.HTTP_409_CONFLICT)

    # Carry warnings forward to include in response
    preflight_warnings = preflight['warnings'] if preflight['status'] == 'warn' else []
    
    # Get target page if this is for a silo
    target_page_title = ''
    target_page_url = ''
    if recommendation.get('silo_id'):
        try:
            target_page = Page.objects.get(id=recommendation['silo_id'])
            target_page_title = target_page.title
            target_page_url = target_page.url
        except Page.DoesNotExist:
            pass
    
    # Generate content
    logger.info(f"Generating content for recommendation {rec_id}: {title} (type={recommendation.get('content_type', 'supporting_article')})")
    logger.info(f"OPENAI_API_KEY set: {bool(os.environ.get('OPENAI_API_KEY', ''))}")
    
    result = generate_supporting_content(
        target_page_title=target_page_title or 'General',
        target_page_url=target_page_url or site.url,
        content_type=recommendation.get('content_type', 'supporting_article'),
        topic=topic,
        business_name=site.name,
        business_type=site.business_type or '',
        service_areas=site.service_areas or [],
    )
    
    if not result.get('success'):
        return Response(
            {'error': result.get('error', 'Content generation failed')},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    # Generate featured image (optional, non-blocking)
    image_data = {}
    if include_image:
        logger.info(f"Generating DALL-E image for: {topic}")
        img_result = generate_content_image(
            topic=topic,
            business_name=site.name,
            content_type=recommendation.get('content_type', 'supporting_article'),
        )
        if img_result.get('success'):
            image_data = {
                'image_url': img_result['image_url'],
                'image_alt_text': img_result['alt_text'],
                'image_caption': img_result['caption'],
                'image_seo_filename': img_result['seo_filename'],
            }

    # Return generated content with recommendation context
    response_data = {
        'recommendation_id': rec_id,
        'title': result['title'],
        'content': result['content'],
        'meta_description': result['meta_description'],
        'suggested_slug': result.get('suggested_slug', ''),
        'word_count': result.get('word_count', 0),
        'silo_id': recommendation.get('silo_id'),
        'status': 'draft',
        'model_used': result.get('model_used'),
        'tokens_used': result.get('tokens_used'),
        **image_data,
    }
    if preflight_warnings:
        response_data['preflight_warnings'] = preflight_warnings
    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_content(request, site_id):
    """
    POST /api/v1/sites/{site_id}/content/approve/
    
    Approve and create a new page from generated content.
    Creates a draft page in the database and triggers WordPress webhook.
    
    Body:
    - title: Page title (required)
    - content: Page content (required)
    - silo_id: Parent silo/money page ID (optional)
    - meta_title: SEO meta title (optional, uses title if not provided)
    - meta_description: SEO meta description (optional)
    - slug: URL slug (optional, will be auto-generated if not provided)
    """
    # Get site and verify ownership
    site = get_object_or_404(Site, id=site_id)
    
    if site.user != request.user:
        return Response(
            {'error': 'Permission denied'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Validate required fields
    title = request.data.get('title')
    content = request.data.get('content')
    
    if not title or not content:
        return Response(
            {'error': 'title and content are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # =========================================================================
    # PREFLIGHT: Cannibalization check before creating the page
    # =========================================================================
    cannibalization_warnings = _check_content_cannibalization(site, title, title)
    if cannibalization_warnings.get('blocked'):
        return Response({
            'error': 'Content would cannibalize existing pages',
            'conflicts': cannibalization_warnings['conflicts'],
            'suggestion': cannibalization_warnings.get('suggestion', 'Choose a different topic or differentiate the angle.'),
        }, status=status.HTTP_409_CONFLICT)
    
    silo_id = request.data.get('silo_id')
    meta_title = request.data.get('meta_title', '').strip() or title
    meta_description = request.data.get('meta_description', '')
    slug = request.data.get('slug', '')
    image_url = request.data.get('image_url', '')
    image_alt_text = request.data.get('image_alt_text', '')
    image_caption = request.data.get('image_caption', '')
    image_seo_filename = request.data.get('image_seo_filename', '')
    
    # Generate slug if not provided
    if not slug:
        slug = title.lower().replace(' ', '-').replace('?', '').replace(':', '')
        # Remove special characters (but preserve / for nested paths)
        slug = ''.join(c for c in slug if c.isalnum() or c in ('-', '/'))
        # Clean up double slashes or leading/trailing
        slug = re.sub(r'/+', '/', slug).strip('/')
    else:
        # User provided a slug — preserve path structure, just clean it
        slug = slug.strip('/')
        slug = '/'.join(
            re.sub(r'[^a-z0-9-]', '', segment)
            for segment in slug.lower().split('/')
            if segment
        )
    
    # Get parent silo if specified
    parent_silo = None
    if silo_id:
        try:
            parent_silo = Page.objects.get(id=silo_id, site=site)
        except Page.DoesNotExist:
            return Response(
                {'error': f'Silo page with ID {silo_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    # Create the page in draft status
    # Note: wp_post_id will be set when WordPress creates the actual post
    page = Page.objects.create(
        site=site,
        title=title,
        content=content,
        slug=slug,
        url=f"{site.url}/{slug}/",  # This will be updated by WordPress
        status='draft',
        post_type='page',
        wp_post_id=0,  # Placeholder - will be updated by webhook
        parent_silo=parent_silo,
        is_money_page=False,
        yoast_title=meta_title,
        yoast_description=meta_description,
    )
    
    logger.info(f"Created draft page {page.id} for site {site.id}: {title}")
    
    # =========================================================================
    # BUG FIX: Push draft to WordPress via webhook
    # Sends POST to {site.url}/wp-json/siloq/v1/webhook with event 'content.create_draft'
    # =========================================================================
    from integrations.wordpress_webhook import send_webhook_to_wordpress

    logger.info(f"Pushing content to WordPress for site {site.id}: {title}")
    
    wp_result = send_webhook_to_wordpress(site, 'content.create_draft', {
        'title': title,
        'content': content,
        'slug': slug,
        'meta_title': meta_title,
        'meta_description': meta_description,
        'siloq_page_id': str(page.id),
        'status': 'draft',
        'parent_silo_id': str(silo_id) if silo_id else None,
    })

    # If WP returned a post ID, persist it
    wp_post_id = None
    wp_edit_url = None
    if wp_result['success'] and wp_result.get('response'):
        wp_post_id = wp_result['response'].get('wp_post_id')
        if wp_post_id:
            page.wp_post_id = int(wp_post_id)
            page.save(update_fields=['wp_post_id'])
            wp_edit_url = f"{site.url}/wp-admin/post.php?post={wp_post_id}&action=edit"
            logger.info(f"WordPress draft created successfully: post ID {wp_post_id}")
    else:
        logger.error(
            f"WordPress webhook failed for site {site.id}: {wp_result.get('error', 'Unknown error')}"
        )

    response_data = {
        'page_id': page.id,
        'title': page.title,
        'slug': page.slug,
        'url': page.url,
        'status': page.status,
        'silo_id': parent_silo.id if parent_silo else None,
        'wordpress_push': {
            'success': wp_result['success'],
            'error': wp_result.get('error'),
            'status_code': wp_result.get('status_code'),
            'wp_post_id': wp_post_id,
            'edit_url': wp_edit_url,
            'webhook_url': f"{site.url.rstrip('/')}/wp-json/siloq/v1/webhook",
        },
        'message': (
            'Page created and pushed to WordPress as draft.'
            if wp_result['success']
            else f"Page created locally. WordPress webhook failed: {wp_result.get('error', 'Unknown error')}. Check that the Siloq plugin is installed and active."
        ),
    }

    # Pass through image data so dashboard/WP plugin can download and attach it
    if image_url:
        response_data.update({
            'image_url': image_url,
            'image_alt_text': image_alt_text,
            'image_caption': image_caption,
            'image_seo_filename': image_seo_filename,
        })

    return Response(response_data, status=status.HTTP_201_CREATED)


def _fallback_recommendations(site: Site) -> List[Dict[str, Any]]:
    """
    Generate basic recommendations when no onboarding data exists.
    Uses existing page titles and site name to infer what content would help.
    """
    recommendations = []
    existing_pages = Page.objects.filter(site=site, status='publish')
    existing_titles = [p.title.lower() for p in existing_pages]
    
    # Extract likely services/topics from existing page titles
    # (pages already on the site hint at what the business does)
    topics = []
    for page in existing_pages[:10]:
        # Use money pages or pages with short titles as topic indicators
        if page.is_money_page or len(page.title.split()) <= 5:
            topics.append(page.title)
    
    if not topics:
        # Use site name as a topic hint
        topics = [site.name]
    
    # Generate FAQ, how-to, and cost guide suggestions
    templates = [
        ('FAQ: Common Questions About {topic}', 'Frequently asked questions help capture voice search and AI citations'),
        ('How Much Does {topic} Cost?', 'Cost pages are among the highest-converting content for service businesses'),
        ('{topic} Checklist: What to Expect', 'Checklist content builds trust and captures "what to expect" searches'),
        ('Why Choose {site_name} for {topic}', 'Differentiator content that builds brand authority'),
        ('Signs You Need {topic}', 'Problem-aware content that captures top-of-funnel searches'),
    ]
    
    for topic in topics[:2]:
        for template_title, reason in templates:
            title = template_title.format(topic=topic, site_name=site.name)
            title_lower = title.lower()
            
            # Skip if similar page already exists
            if any(title_lower in et or et in title_lower for et in existing_titles):
                continue
            
            rec_id = _generate_rec_id(site.id, title)
            recommendations.append({
                'id': rec_id,
                'title': title,
                'silo': topic,
                'silo_id': None,
                'reason': reason,
                'priority': 'medium',
                'content_type': 'supporting_article',
                'estimated_searches': None,
            })
    
    return recommendations[:8]  # Cap at 8


# ─────────────────────────────────────────────────────────────
# Content Upload (user-written articles)
# ─────────────────────────────────────────────────────────────

def _extract_file_content(uploaded_file) -> str:
    """Extract text content from an uploaded file (.txt, .html, .docx)."""
    name = (uploaded_file.name or '').lower()
    raw = uploaded_file.read()

    if name.endswith('.docx'):
        try:
            from docx import Document
            doc = Document(io.BytesIO(raw))
            return '\n'.join(p.text for p in doc.paragraphs)
        except ImportError:
            # python-docx not installed — return raw decoded text
            return raw.decode('utf-8', errors='replace')

    # .txt, .html, or anything else — read as text
    return raw.decode('utf-8', errors='replace')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def upload_content(request, site_id):
    """
    POST /api/v1/sites/{site_id}/content/upload/

    Accept user-written content, run preflight validation, save for review.

    Body (JSON or multipart):
    - title: str (required)
    - content: str (required — HTML or plain text; ignored if `file` is provided)
    - file: uploaded file (.txt/.html/.docx) — alternative to `content`
    - slug: str (optional — auto-generated from title if missing)
    - target_keyword: str (optional)
    - silo_id: int (optional — which silo this belongs to)
    - meta_title: str (optional — SEO meta title, separate from H1)
    - meta_description: str (optional)
    - excerpt: str (optional)
    - images[]: uploaded image files (optional, up to 10)
    - image_alts[]: alt text for each image (optional)
    - image_captions[]: captions for each image (optional)

    Returns:
    - id, title, slug, preflight_result, status ('pending_review')
    - If smart parser detected city page format: parsed fields returned
    - If preflight blocks: returns the blocking checks with explanations
    """
    site = get_object_or_404(Site, id=site_id)

    if site.user != request.user:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

    # ── Required fields ──────────────────────────────────────
    title = request.data.get('title', '').strip()
    content = request.data.get('content', '').strip()

    # File upload takes precedence over content field
    uploaded_file = request.FILES.get('file')
    parsed_data = None
    if uploaded_file:
        try:
            raw_content = _extract_file_content(uploaded_file)
            
            # ══════════════════════════════════════════════════════
            # Feature 3: Smart Content Parser for City Page Docs
            # ══════════════════════════════════════════════════════
            if 'Backend & Meta Data' in raw_content and 'On-Page Content' in raw_content:
                parsed_data = _parse_city_page_doc(raw_content)
                content = parsed_data['content_html']
                logger.info(f"Smart parser detected city page format for site {site.id}")
            else:
                content = raw_content
        except Exception as e:
            return Response(
                {'error': f'Failed to read uploaded file: {e}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if not title:
        return Response({'error': 'title is required'}, status=status.HTTP_400_BAD_REQUEST)
    if not content:
        return Response(
            {'error': 'content is required (provide content field or upload a file)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── Optional fields ──────────────────────────────────────
    # If smart parser detected city page format, use parsed values
    slug = request.data.get('slug', '').strip()
    if parsed_data and parsed_data.get('slug'):
        slug = parsed_data['slug']
    elif not slug:
        slug = slugify(title)[:200]
    else:
        # Preserve path structure (e.g., service-area/blue-springs-mo)
        slug = slug.strip('/')
        slug = '/'.join(
            slugify(segment) for segment in slug.split('/') if segment
        )

    target_keyword = request.data.get('target_keyword', '').strip() or title
    silo_id = request.data.get('silo_id')
    
    meta_title = request.data.get('meta_title', '').strip()
    if parsed_data and parsed_data.get('meta_title'):
        meta_title = parsed_data['meta_title']
    
    meta_description = request.data.get('meta_description', '').strip()
    if parsed_data and parsed_data.get('meta_description'):
        meta_description = parsed_data['meta_description']
    
    excerpt = request.data.get('excerpt', '').strip()
    
    # ══════════════════════════════════════════════════════════
    # Feature 2: Image Upload with Alt Text
    # ══════════════════════════════════════════════════════════
    images = request.FILES.getlist('images[]') or request.FILES.getlist('images')
    image_alts = request.data.getlist('image_alts[]') or request.data.getlist('image_alts') or []
    image_captions = request.data.getlist('image_captions[]') or request.data.getlist('image_captions') or []
    
    # Encode images as base64 for WordPress webhook
    images_data = []
    for idx, img_file in enumerate(images[:10]):  # Limit to 10 images
        try:
            img_bytes = img_file.read()
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
            alt_text = image_alts[idx] if idx < len(image_alts) else ''
            caption = image_captions[idx] if idx < len(image_captions) else ''
            
            # Slugify alt text for filename
            filename_base = slugify(alt_text)[:50] if alt_text else f'image-{idx+1}'
            filename = f"{filename_base}.{img_file.name.split('.')[-1]}"
            
            images_data.append({
                'data': img_base64,
                'alt': alt_text,
                'caption': caption,
                'filename': filename,
                'mime_type': img_file.content_type,
            })
        except Exception as e:
            logger.error(f"Failed to encode image {idx}: {e}")
    
    logger.info(f"Uploaded {len(images_data)} images for site {site.id}")

    # ── Preflight validation ─────────────────────────────────
    preflight_result = run_preflight_validation(
        site=site,
        proposed_title=title,
        proposed_keyword=target_keyword,
        proposed_slug=slug,
        proposed_h1=title,
        silo_id=silo_id,
        page_type='spoke',
    )

    # If preflight blocks, return the conflicts but don't save
    if preflight_result.get('status') == 'block':
        return Response({
            'error': 'Content blocked by preflight validation',
            'preflight_result': preflight_result,
            'title': title,
            'slug': slug,
        }, status=status.HTTP_409_CONFLICT)

    # ── Resolve parent silo ──────────────────────────────────
    parent_silo = None
    if silo_id:
        try:
            parent_silo = Page.objects.get(id=silo_id, site=site)
        except Page.DoesNotExist:
            return Response(
                {'error': f'Silo page with ID {silo_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

    # ── Save as draft page (same shape approve_content uses) ─
    page = Page.objects.create(
        site=site,
        title=title,
        content=content,
        slug=slug,
        url=f"{site.url}/{slug}/",
        status='draft',
        post_type='page',
        wp_post_id=0,
        parent_silo=parent_silo,
        is_money_page=False,
        yoast_title=meta_title or title,
        yoast_description=meta_description,
        excerpt=excerpt,
    )

    logger.info(f"Uploaded content saved as draft page {page.id} for site {site.id}: {title}")

    response_data = {
        'id': page.id,
        'content_id': page.id,  # For approve endpoint
        'title': page.title,
        'slug': page.slug,
        'url': page.url,
        'status': 'pending_review',
        'can_approve': preflight_result.get('status') != 'block',
        'silo_id': parent_silo.id if parent_silo else None,
        'meta_title': meta_title,
        'meta_description': meta_description,
        'excerpt': excerpt,
        'target_keyword': target_keyword,
        'checks': preflight_result.get('checks', []),
        'preflight': preflight_result.get('checks', []),
        'message': 'Content uploaded and saved for review. Use the approve endpoint to push to WordPress.',
    }
    
    # If smart parser was used, include parsed fields
    if parsed_data:
        response_data['smart_parsed'] = True
        response_data['parsed_fields'] = {
            'slug': parsed_data.get('slug', ''),
            'meta_title': parsed_data.get('meta_title', ''),
            'meta_description': parsed_data.get('meta_description', ''),
        }
    
    # Include image data if any
    if images_data:
        response_data['images'] = images_data
        response_data['image_count'] = len(images_data)
    
    return Response(response_data, status=status.HTTP_201_CREATED)
