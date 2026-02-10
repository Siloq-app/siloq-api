"""
Internal Link Analysis Engine

Analyzes internal linking structure for:
- Anchor text conflicts (same anchor → different pages)
- Homepage anchor theft (target keywords linking to homepage)
- Missing target links (supporting pages not linking to their target)
- Missing sibling links (supporting pages not interlinking)
- Orphan pages (no incoming internal links)
- Cross-silo links (links between different silos)
- Silo health (proper link flow)
"""
import re
from collections import defaultdict
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from django.db.models import Count, Q

from .models import Page, InternalLink, AnchorTextConflict, LinkIssue


# Maximum supporting pages per target (governance rule)
MAX_SUPPORTING_PAGES = 7


def extract_links_from_content(content: str, page_url: str, site_domain: str) -> List[Dict[str, Any]]:
    """
    Extract all links from HTML content.
    
    Returns list of dicts with:
    - url: The target URL
    - anchor_text: The clickable text
    - is_internal: Whether it's an internal link
    - is_nofollow: Whether it has rel=nofollow
    - context: Surrounding text
    """
    if not content:
        return []
    
    soup = BeautifulSoup(content, 'html.parser')
    links = []
    
    for a_tag in soup.find_all('a', href=True):
        href = a_tag.get('href', '').strip()
        if not href or href.startswith('#') or href.startswith('javascript:'):
            continue
        
        # Normalize URL
        if href.startswith('/'):
            full_url = urljoin(f"https://{site_domain}", href)
        elif not href.startswith(('http://', 'https://')):
            full_url = urljoin(page_url, href)
        else:
            full_url = href
        
        # Check if internal
        parsed = urlparse(full_url)
        is_internal = site_domain.lower() in parsed.netloc.lower()
        
        # Get anchor text
        anchor_text = a_tag.get_text(strip=True)
        
        # Check for nofollow
        rel = a_tag.get('rel', [])
        if isinstance(rel, str):
            rel = rel.split()
        is_nofollow = 'nofollow' in rel
        
        # Get surrounding context
        context = ''
        parent = a_tag.parent
        if parent:
            context_text = parent.get_text(strip=True)
            # Limit context to ±100 chars around anchor
            anchor_pos = context_text.find(anchor_text)
            if anchor_pos >= 0:
                start = max(0, anchor_pos - 50)
                end = min(len(context_text), anchor_pos + len(anchor_text) + 50)
                context = context_text[start:end]
        
        links.append({
            'url': full_url,
            'anchor_text': anchor_text,
            'is_internal': is_internal,
            'is_nofollow': is_nofollow,
            'context': context,
        })
    
    return links


def sync_internal_links(page: Page) -> int:
    """
    Extract and store internal links from a page's content.
    Returns the number of internal links found.
    """
    from sites.models import Site
    
    site = page.site
    site_domain = urlparse(site.url).netloc
    
    # Clear existing links from this page
    InternalLink.objects.filter(source_page=page).delete()
    
    # Extract links
    links = extract_links_from_content(page.content, page.url, site_domain)
    internal_links = [l for l in links if l['is_internal']]
    
    # Store internal links
    for link_data in internal_links:
        # Try to find target page in database
        target_url = link_data['url'].rstrip('/')
        target_page = Page.objects.filter(
            site=site,
            url__icontains=urlparse(target_url).path.rstrip('/')
        ).first()
        
        InternalLink.objects.create(
            site=site,
            source_page=page,
            target_page=target_page,
            target_url=link_data['url'],
            anchor_text=link_data['anchor_text'][:500] if link_data['anchor_text'] else '',
            context_text=link_data['context'][:1000] if link_data['context'] else '',
            is_nofollow=link_data['is_nofollow'],
            is_valid=target_page is not None,
        )
    
    return len(internal_links)


def detect_anchor_conflicts(site) -> List[Dict[str, Any]]:
    """
    Find anchor texts that link to multiple different pages.
    This is a governance violation - same keyword should point to ONE target.
    """
    # Group links by normalized anchor text
    anchor_groups = defaultdict(set)
    anchor_counts = defaultdict(int)
    
    links = InternalLink.objects.filter(
        site=site,
        target_page__isnull=False,
        anchor_text_normalized__gt=''  # Non-empty anchors
    ).select_related('target_page')
    
    for link in links:
        if len(link.anchor_text_normalized) >= 3:  # Skip very short anchors
            anchor_groups[link.anchor_text_normalized].add(link.target_page_id)
            anchor_counts[link.anchor_text_normalized] += 1
    
    # Find conflicts (same anchor → multiple pages)
    conflicts = []
    for anchor, page_ids in anchor_groups.items():
        if len(page_ids) > 1:
            pages = Page.objects.filter(id__in=page_ids)
            
            # Determine severity
            has_money_page = any(p.is_money_page for p in pages)
            severity = 'high' if has_money_page else 'medium'
            
            conflicts.append({
                'anchor_text': anchor,
                'target_pages': [
                    {'id': p.id, 'url': p.url, 'title': p.title, 'is_money_page': p.is_money_page}
                    for p in pages
                ],
                'occurrence_count': anchor_counts[anchor],
                'severity': severity,
            })
    
    return sorted(conflicts, key=lambda x: (-len(x['target_pages']), -x['occurrence_count']))


def detect_homepage_anchor_theft(site) -> List[Dict[str, Any]]:
    """
    Find cases where target/commercial keywords link to the homepage
    instead of their proper target page.
    """
    issues = []
    
    # Get homepage
    homepage = Page.objects.filter(site=site, is_homepage=True).first()
    if not homepage:
        # Try to detect homepage by URL pattern
        homepage = Page.objects.filter(
            site=site,
            url__regex=r'^https?://[^/]+/?$'
        ).first()
    
    if not homepage:
        return []
    
    # Get all money pages and their target keywords
    money_pages = Page.objects.filter(site=site, is_money_page=True)
    target_keywords = set()
    
    for mp in money_pages:
        # Extract potential target keywords from title and URL
        keywords = extract_keywords_from_title(mp.title)
        target_keywords.update(keywords)
    
    # Find links to homepage with target keywords as anchor
    homepage_links = InternalLink.objects.filter(
        site=site,
        target_page=homepage,
        anchor_text_normalized__gt=''
    )
    
    for link in homepage_links:
        anchor_lower = link.anchor_text_normalized
        for keyword in target_keywords:
            if keyword.lower() in anchor_lower or anchor_lower in keyword.lower():
                # Find which money page should get this anchor
                matching_money_page = None
                for mp in money_pages:
                    if keyword.lower() in mp.title.lower():
                        matching_money_page = mp
                        break
                
                issues.append({
                    'anchor_text': link.anchor_text,
                    'source_page': {
                        'id': link.source_page.id,
                        'url': link.source_page.url,
                        'title': link.source_page.title,
                    },
                    'should_link_to': {
                        'id': matching_money_page.id,
                        'url': matching_money_page.url,
                        'title': matching_money_page.title,
                    } if matching_money_page else None,
                    'severity': 'high',
                })
                break
    
    return issues


def detect_missing_target_links(site) -> List[Dict[str, Any]]:
    """
    Find supporting pages that don't link to their target (money) page.
    """
    issues = []
    
    # Get all supporting pages with assigned silos
    supporting_pages = Page.objects.filter(
        site=site,
        parent_silo__isnull=False
    ).select_related('parent_silo')
    
    for page in supporting_pages:
        target = page.parent_silo
        
        # Check if this page links to its target
        has_link = InternalLink.objects.filter(
            source_page=page,
            target_page=target
        ).exists()
        
        if not has_link:
            issues.append({
                'supporting_page': {
                    'id': page.id,
                    'url': page.url,
                    'title': page.title,
                },
                'target_page': {
                    'id': target.id,
                    'url': target.url,
                    'title': target.title,
                },
                'severity': 'high',
                'recommendation': f"Add a link from '{page.title}' to '{target.title}' using relevant anchor text.",
            })
    
    return issues


def detect_missing_sibling_links(site) -> List[Dict[str, Any]]:
    """
    Find supporting pages that don't interlink with their siblings.
    Supporting pages in the same silo should link to each other for topical authority.
    """
    issues = []
    
    # Group supporting pages by their target (silo)
    silos = defaultdict(list)
    supporting_pages = Page.objects.filter(
        site=site,
        parent_silo__isnull=False
    )
    
    for page in supporting_pages:
        silos[page.parent_silo_id].append(page)
    
    # Check each silo
    for target_id, pages in silos.items():
        if len(pages) < 2:
            continue  # Need at least 2 pages to interlink
        
        for page in pages:
            siblings = [p for p in pages if p.id != page.id]
            
            # Check links to siblings
            sibling_ids = [s.id for s in siblings]
            links_to_siblings = InternalLink.objects.filter(
                source_page=page,
                target_page_id__in=sibling_ids
            ).count()
            
            # Should link to at least half of siblings, or all if few
            min_links = max(1, len(siblings) // 2)
            
            if links_to_siblings < min_links:
                target = Page.objects.get(id=target_id)
                missing_siblings = [
                    s for s in siblings
                    if not InternalLink.objects.filter(source_page=page, target_page=s).exists()
                ]
                
                issues.append({
                    'page': {
                        'id': page.id,
                        'url': page.url,
                        'title': page.title,
                    },
                    'silo': {
                        'id': target.id,
                        'title': target.title,
                    },
                    'links_to_siblings': links_to_siblings,
                    'total_siblings': len(siblings),
                    'missing_links_to': [
                        {'id': s.id, 'url': s.url, 'title': s.title}
                        for s in missing_siblings[:3]  # Limit to top 3
                    ],
                    'severity': 'medium',
                })
    
    return issues


def detect_orphan_pages(site) -> List[Dict[str, Any]]:
    """
    Find pages with no incoming internal links (orphans).
    """
    # Get pages with no incoming links
    pages_with_links = InternalLink.objects.filter(
        site=site,
        target_page__isnull=False
    ).values_list('target_page_id', flat=True).distinct()
    
    orphans = Page.objects.filter(
        site=site,
        status='publish'
    ).exclude(
        id__in=pages_with_links
    ).exclude(
        is_homepage=True  # Homepage doesn't need incoming internal links
    )
    
    return [
        {
            'page': {
                'id': p.id,
                'url': p.url,
                'title': p.title,
                'is_money_page': p.is_money_page,
            },
            'severity': 'high' if p.is_money_page else 'medium',
            'recommendation': f"Add internal links pointing to '{p.title}' from relevant pages.",
        }
        for p in orphans
    ]


def detect_silo_size_issues(site) -> List[Dict[str, Any]]:
    """
    Check if any silos have too many supporting pages (>7).
    """
    issues = []
    
    money_pages = Page.objects.filter(site=site, is_money_page=True)
    
    for mp in money_pages:
        supporting_count = Page.objects.filter(parent_silo=mp).count()
        
        if supporting_count > MAX_SUPPORTING_PAGES:
            issues.append({
                'target_page': {
                    'id': mp.id,
                    'url': mp.url,
                    'title': mp.title,
                },
                'supporting_count': supporting_count,
                'max_allowed': MAX_SUPPORTING_PAGES,
                'severity': 'medium',
                'recommendation': f"Consider splitting this silo. {supporting_count} supporting pages is above the recommended {MAX_SUPPORTING_PAGES}.",
            })
    
    return issues


def calculate_link_health_score(site) -> Dict[str, Any]:
    """
    Calculate overall internal linking health score for a site.
    
    Returns:
    {
        'score': 0-100,
        'breakdown': {
            'anchor_conflicts': {'score': X, 'issues': N},
            'target_links': {'score': X, 'issues': N},
            'sibling_links': {'score': X, 'issues': N},
            'orphan_pages': {'score': X, 'issues': N},
        }
    }
    """
    scores = {}
    
    # Check anchor conflicts (30% weight)
    anchor_conflicts = detect_anchor_conflicts(site)
    anchor_score = max(0, 100 - (len(anchor_conflicts) * 15))
    scores['anchor_conflicts'] = {
        'score': anchor_score,
        'issues': len(anchor_conflicts),
        'weight': 0.30,
    }
    
    # Check homepage theft (20% weight)
    homepage_theft = detect_homepage_anchor_theft(site)
    homepage_score = max(0, 100 - (len(homepage_theft) * 20))
    scores['homepage_protection'] = {
        'score': homepage_score,
        'issues': len(homepage_theft),
        'weight': 0.20,
    }
    
    # Check missing target links (25% weight)
    missing_targets = detect_missing_target_links(site)
    total_supporting = Page.objects.filter(site=site, parent_silo__isnull=False).count()
    if total_supporting > 0:
        target_score = max(0, 100 - (len(missing_targets) / total_supporting * 100))
    else:
        target_score = 100
    scores['target_links'] = {
        'score': target_score,
        'issues': len(missing_targets),
        'weight': 0.25,
    }
    
    # Check orphan pages (25% weight)
    orphans = detect_orphan_pages(site)
    total_pages = Page.objects.filter(site=site, status='publish').count()
    if total_pages > 0:
        orphan_score = max(0, 100 - (len(orphans) / total_pages * 100))
    else:
        orphan_score = 100
    scores['orphan_pages'] = {
        'score': orphan_score,
        'issues': len(orphans),
        'weight': 0.25,
    }
    
    # Calculate weighted total
    total_score = sum(s['score'] * s['weight'] for s in scores.values())
    
    return {
        'score': round(total_score),
        'breakdown': scores,
        'total_issues': sum(s['issues'] for s in scores.values()),
    }


def get_silo_structure(site) -> List[Dict[str, Any]]:
    """
    Get the complete silo structure for visualization.
    
    Returns hierarchical structure:
    - Homepage at top
    - Target pages (money pages)
    - Supporting pages under each target
    - Links between pages
    """
    # Get homepage
    homepage = Page.objects.filter(site=site, is_homepage=True).first()
    if not homepage:
        homepage = Page.objects.filter(
            site=site,
            url__regex=r'^https?://[^/]+/?$'
        ).first()
    
    # Get target pages (money pages)
    money_pages = Page.objects.filter(
        site=site, 
        is_money_page=True
    ).prefetch_related('supporting_pages', 'incoming_links', 'outgoing_links')
    
    silos = []
    for mp in money_pages:
        supporting = Page.objects.filter(parent_silo=mp)
        
        # Get links within this silo
        silo_page_ids = [mp.id] + list(supporting.values_list('id', flat=True))
        internal_links = InternalLink.objects.filter(
            source_page_id__in=silo_page_ids,
            target_page_id__in=silo_page_ids
        ).select_related('source_page', 'target_page')
        
        silos.append({
            'target': {
                'id': mp.id,
                'url': mp.url,
                'title': mp.title,
                'slug': mp.slug,
            },
            'supporting_pages': [
                {
                    'id': sp.id,
                    'url': sp.url,
                    'title': sp.title,
                    'slug': sp.slug,
                }
                for sp in supporting
            ],
            'supporting_count': supporting.count(),
            'links': [
                {
                    'source_id': link.source_page_id,
                    'target_id': link.target_page_id,
                    'anchor_text': link.anchor_text,
                }
                for link in internal_links
            ],
        })
    
    return {
        'homepage': {
            'id': homepage.id,
            'url': homepage.url,
            'title': homepage.title,
        } if homepage else None,
        'silos': silos,
        'total_target_pages': len(silos),
        'total_supporting_pages': sum(s['supporting_count'] for s in silos),
    }


def extract_keywords_from_title(title: str) -> List[str]:
    """
    Extract potential target keywords from a page title.
    """
    if not title:
        return []
    
    # Remove common suffixes
    title = re.sub(r'\s*[-|–—]\s*[^-|–—]+$', '', title)
    
    # Split into words and create phrases
    words = title.lower().split()
    keywords = []
    
    # Single words (3+ chars)
    keywords.extend([w for w in words if len(w) >= 3])
    
    # 2-word phrases
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i+1]}"
        if len(phrase) >= 5:
            keywords.append(phrase)
    
    # 3-word phrases
    for i in range(len(words) - 2):
        phrase = f"{words[i]} {words[i+1]} {words[i+2]}"
        keywords.append(phrase)
    
    return keywords


def analyze_internal_links(site) -> Dict[str, Any]:
    """
    Run complete internal link analysis for a site.
    
    Returns comprehensive analysis with:
    - Health score
    - All issues by type
    - Silo structure
    - Recommendations
    """
    # Calculate health
    health = calculate_link_health_score(site)
    
    # Get all issues
    issues = {
        'anchor_conflicts': detect_anchor_conflicts(site),
        'homepage_theft': detect_homepage_anchor_theft(site),
        'missing_target_links': detect_missing_target_links(site),
        'missing_sibling_links': detect_missing_sibling_links(site),
        'orphan_pages': detect_orphan_pages(site),
        'silo_size_issues': detect_silo_size_issues(site),
    }
    
    # Get structure
    structure = get_silo_structure(site)
    
    # Generate top recommendations
    recommendations = []
    
    if issues['anchor_conflicts']:
        recommendations.append({
            'type': 'anchor_conflict',
            'priority': 'high',
            'message': f"Fix {len(issues['anchor_conflicts'])} anchor text conflicts - same keywords linking to multiple pages.",
        })
    
    if issues['homepage_theft']:
        recommendations.append({
            'type': 'homepage_theft',
            'priority': 'high',
            'message': f"Fix {len(issues['homepage_theft'])} cases of target keywords linking to homepage instead of their target page.",
        })
    
    if issues['missing_target_links']:
        recommendations.append({
            'type': 'missing_target_links',
            'priority': 'high',
            'message': f"Add {len(issues['missing_target_links'])} missing links from supporting pages to their target pages.",
        })
    
    if issues['orphan_pages']:
        recommendations.append({
            'type': 'orphan_pages',
            'priority': 'medium',
            'message': f"Add internal links to {len(issues['orphan_pages'])} orphan pages.",
        })
    
    return {
        'health_score': health['score'],
        'health_breakdown': health['breakdown'],
        'total_issues': health['total_issues'],
        'issues': issues,
        'structure': structure,
        'recommendations': recommendations,
    }


def generate_content_suggestions(site) -> Dict[str, Any]:
    """
    Generate content suggestions for a site based on target pages.
    
    For each target (money) page, suggests supporting content topics.
    Uses keyword analysis and content gap detection.
    """
    from .models import Page
    
    pages = Page.objects.filter(site=site)
    target_pages = pages.filter(is_money_page=True)
    supporting_pages = pages.filter(parent_silo__isnull=False)
    
    suggestions = []
    
    for target in target_pages:
        # Extract keywords from target
        keywords = extract_keywords_from_title(target.title)
        primary_keyword = keywords[0] if keywords else target.title.lower()
        
        # Get existing supporting pages for this target
        existing_supporting = supporting_pages.filter(parent_silo=target)
        existing_titles = [p.title.lower() for p in existing_supporting]
        
        # Generate topic suggestions
        topic_ideas = []
        
        # 1. Question-based content
        question_templates = [
            f"What is {primary_keyword}",
            f"How to {primary_keyword}",
            f"Why {primary_keyword} matters",
            f"Benefits of {primary_keyword}",
            f"{primary_keyword.title()} guide for beginners",
            f"Common {primary_keyword} mistakes to avoid",
            f"{primary_keyword.title()} best practices",
            f"How much does {primary_keyword} cost",
        ]
        
        # 2. Comparison/alternative content
        comparison_templates = [
            f"{primary_keyword.title()} vs alternatives",
            f"Types of {primary_keyword}",
            f"Best {primary_keyword} options",
            f"{primary_keyword.title()} comparison",
        ]
        
        # 3. Local/specific variations (if applicable)
        local_templates = [
            f"{primary_keyword.title()} near me",
            f"Local {primary_keyword} services",
            f"{primary_keyword.title()} in [city]",
        ]
        
        # 4. Process/step content
        process_templates = [
            f"{primary_keyword.title()} process explained",
            f"Step-by-step {primary_keyword}",
            f"What to expect from {primary_keyword}",
            f"Preparing for {primary_keyword}",
        ]
        
        all_templates = (
            question_templates[:4] +  # Top 4 questions
            comparison_templates[:2] +  # Top 2 comparisons
            process_templates[:2]  # Top 2 process
        )
        
        for template in all_templates:
            # Check if similar content already exists
            template_lower = template.lower()
            already_exists = any(
                similar_content(template_lower, existing) 
                for existing in existing_titles
            )
            
            if not already_exists:
                topic_ideas.append({
                    'title': template,
                    'type': categorize_content_type(template),
                    'target_keyword': primary_keyword,
                    'priority': calculate_content_priority(template, primary_keyword),
                })
        
        # Sort by priority
        topic_ideas.sort(key=lambda x: -x['priority'])
        
        suggestions.append({
            'target_page': {
                'id': target.id,
                'title': target.title,
                'url': target.url,
            },
            'existing_supporting_count': existing_supporting.count(),
            'suggested_topics': topic_ideas[:6],  # Top 6 suggestions
            'gap_analysis': {
                'has_how_to': any('how to' in t.lower() for t in existing_titles),
                'has_comparison': any('vs' in t.lower() or 'comparison' in t.lower() for t in existing_titles),
                'has_guide': any('guide' in t.lower() for t in existing_titles),
                'has_faq': any('faq' in t.lower() or 'question' in t.lower() for t in existing_titles),
            }
        })
    
    return {
        'suggestions': suggestions,
        'total_targets': len(suggestions),
        'total_suggested_topics': sum(len(s['suggested_topics']) for s in suggestions),
    }


def similar_content(title1: str, title2: str) -> bool:
    """Check if two titles are similar enough to be considered duplicates."""
    # Simple word overlap check
    words1 = set(title1.lower().split())
    words2 = set(title2.lower().split())
    
    # Remove common stop words
    stop_words = {'the', 'a', 'an', 'is', 'are', 'to', 'for', 'of', 'and', 'in', 'on', 'with'}
    words1 = words1 - stop_words
    words2 = words2 - stop_words
    
    if not words1 or not words2:
        return False
    
    # Calculate Jaccard similarity
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    similarity = intersection / union if union > 0 else 0
    
    return similarity > 0.5  # 50% word overlap


def categorize_content_type(title: str) -> str:
    """Categorize content suggestion by type."""
    title_lower = title.lower()
    
    if any(q in title_lower for q in ['what is', 'why', 'how much', 'when']):
        return 'educational'
    elif any(q in title_lower for q in ['how to', 'guide', 'step']):
        return 'how-to'
    elif any(q in title_lower for q in ['vs', 'comparison', 'alternative', 'best']):
        return 'comparison'
    elif any(q in title_lower for q in ['mistake', 'avoid', 'tip', 'practice']):
        return 'tips'
    elif any(q in title_lower for q in ['cost', 'price', 'budget']):
        return 'commercial'
    elif any(q in title_lower for q in ['near me', 'local', 'in [']):
        return 'local'
    else:
        return 'general'


def calculate_content_priority(title: str, keyword: str) -> int:
    """Calculate priority score for content suggestion."""
    score = 50  # Base score
    title_lower = title.lower()
    
    # Boost for how-to content (high search intent)
    if 'how to' in title_lower:
        score += 20
    
    # Boost for beginner content (broad appeal)
    if 'beginner' in title_lower or 'guide' in title_lower:
        score += 15
    
    # Boost for cost/price content (commercial intent)
    if 'cost' in title_lower or 'price' in title_lower:
        score += 25
    
    # Boost for comparison content (decision stage)
    if 'vs' in title_lower or 'comparison' in title_lower:
        score += 20
    
    # Boost for mistake/avoid content (problem-aware)
    if 'mistake' in title_lower or 'avoid' in title_lower:
        score += 10
    
    # Boost for best/top content
    if 'best' in title_lower:
        score += 15
    
    return score
