"""
Supporting Content Gap Detection & Content Plan Generation
Section 02 — Siloq V1 Spec

GET  /api/v1/sites/{site_id}/pages/{page_id}/supporting-content/
     → Detect gap, return supporting pages + generated topic plan

POST /api/v1/sites/{site_id}/pages/{page_id}/supporting-content/generate/
     → Generate full article for an approved topic

GET  /api/v1/sites/{site_id}/pages/{page_id}/about-analysis/
     → About Us intelligence: E-E-A-T check, team presence, social links
"""
import re
import logging
import os
from urllib.parse import urlparse

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import Page, InternalLink, SiteEntityProfile
from seo.profile_validators import get_profile_completeness

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# Minimum supporting pages before we flag a money page as under-supported
MIN_SUPPORTING_PAGES = 2

# Money page types that benefit from supporting content
MONEY_PAGE_TYPES = {'money', 'service', 'service_hub', 'location', 'product'}


# =============================================================================
# SUPPORTING CONTENT GAP DETECTION
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def supporting_content_gap(request, site_id: int, page_id: int):
    """
    GET /api/v1/sites/{site_id}/pages/{page_id}/supporting-content/

    Returns:
    - supporting_pages: list of pages that link TO this page
    - gap_count: how many more supporting pages are needed
    - missing_supporting_content: bool
    - topic_plan: list of 3-5 business-specific article topics
    - profile_completeness: partial check for topic generation blocking
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    page = get_object_or_404(Page, id=page_id, site=site)

    # ── 1. Find pages that link TO this page via InternalLink ─────────────────
    incoming = (
        InternalLink.objects
        .filter(site=site, target_page=page, is_valid=True)
        .select_related('source_page')
        .values(
            'source_page__id',
            'source_page__title',
            'source_page__url',
            'source_page__page_type_classification',
            'anchor_text',
        )
    )

    supporting_pages = []
    seen_source_ids = set()
    for link in incoming:
        src_id = link['source_page__id']
        if src_id and src_id not in seen_source_ids:
            seen_source_ids.add(src_id)
            supporting_pages.append({
                'page_id':   src_id,
                'title':     link['source_page__title'],
                'url':       link['source_page__url'],
                'page_type': link['source_page__page_type_classification'],
                'anchor_text': link['anchor_text'],
            })

    current_count = len(supporting_pages)
    missing_supporting_content = current_count < MIN_SUPPORTING_PAGES

    # ── 2. Get entity profile for topic generation ────────────────────────────
    try:
        profile = SiteEntityProfile.objects.get(site=site)
    except SiteEntityProfile.DoesNotExist:
        profile = None

    completeness = get_profile_completeness(profile) if profile else {
        'content_blocked': True,
        'missing_required': ['business_name', 'address_or_service_area'],
        'blocked_features': ['content_topic_generation'],
    }

    topic_plan = []
    if not completeness.get('content_blocked') and missing_supporting_content:
        topic_plan = _generate_topic_plan(page, profile, site)

    return Response({
        'page_id':    page.id,
        'page_url':   page.url,
        'page_title': page.title,
        'page_type':  page.page_type_classification,
        'supporting_pages':          supporting_pages,
        'supporting_page_count':     current_count,
        'min_recommended':           MIN_SUPPORTING_PAGES,
        'missing_supporting_content': missing_supporting_content,
        'gap_count': max(0, MIN_SUPPORTING_PAGES - current_count),
        'topic_plan': topic_plan,
        'profile_completeness': {
            'content_blocked':   completeness.get('content_blocked', False),
            'missing_required':  completeness.get('missing_required', []),
            'blocked_features':  completeness.get('blocked_features', []),
        },
    })


def _generate_topic_plan(page: Page, profile, site: Site) -> list:
    """
    Generate 3-5 business-specific article topics for a money page.
    Uses the entity profile: services, brands_used, service_cities, primary GSC query.
    """
    business_name  = getattr(profile, 'business_name', '') or site.name
    services       = getattr(profile, 'categories', []) or []
    brands_used    = getattr(profile, 'brands_used', []) or []
    service_cities = getattr(profile, 'service_cities', []) or []
    city           = service_cities[0] if service_cities else (getattr(profile, 'city', '') or '')
    state          = getattr(profile, 'state', '') or ''
    location       = f"{city}, {state}".strip(', ') if city or state else ''

    # Primary service from page title or first category
    primary_service = services[0] if services else _extract_primary_topic(page.title)

    topics = []

    # Formula 1: Brand + service + location
    if brands_used:
        brand = brands_used[0]
        topics.append({
            'title':          f"{brand} {primary_service} in {location} — What to Expect" if location else f"{brand} {primary_service} — What Customers Need to Know",
            'target_keyword': f"{brand.lower()} {primary_service.lower()} {city.lower()}".strip(),
            'content_type':   'supporting_article',
            'word_count':     1200,
            'supports_page':  page.title,
            'supports_url':   page.url,
            'rationale':      f"Brand-specific article builds topical authority for {brand} and drives qualified traffic to your {primary_service} page.",
        })

    # Formula 2: Problem + location
    topics.append({
        'title':          f"{_problem_hook(primary_service)} in {location}? Here's What That Means" if location else f"{_problem_hook(primary_service)}? Here's What to Do",
        'target_keyword': f"{_problem_hook(primary_service).lower()} {city.lower()}".strip(),
        'content_type':   'supporting_article',
        'word_count':     900,
        'supports_page':  page.title,
        'supports_url':   page.url,
        'rationale':      "Problem-aware searchers are high intent. This article captures them before they find a competitor.",
    })

    # Formula 3: Cost + location
    topics.append({
        'title':          f"How Much Does {primary_service} Cost in {location}?" if location else f"How Much Does {primary_service} Cost?",
        'target_keyword': f"{primary_service.lower()} cost {city.lower()}".strip() or f"how much does {primary_service.lower()} cost",
        'content_type':   'faq',
        'word_count':     800,
        'supports_page':  page.title,
        'supports_url':   page.url,
        'rationale':      "Cost/pricing queries are high-intent and underserved. FAQ schema on this article triggers rich results.",
    })

    # Formula 4: Brand comparison (only if 2+ brands)
    if len(brands_used) >= 2:
        brand_a, brand_b = brands_used[0], brands_used[1]
        business_type = _business_type_label(services)
        topics.append({
            'title':          f"{brand_a} vs {brand_b}: A {location} {business_type} Compares" if location else f"{brand_a} vs {brand_b} — Which Is Better?",
            'target_keyword': f"{brand_a.lower()} vs {brand_b.lower()} {city.lower()}".strip(),
            'content_type':   'comparison',
            'word_count':     1400,
            'supports_page':  page.title,
            'supports_url':   page.url,
            'rationale':      f"Comparison articles rank for high-intent 'which is better' queries and build your authority on both {brand_a} and {brand_b}.",
        })

    # Formula 5: Permit/FAQ from GSC-style queries
    topics.append({
        'title':          f"Do I Need a Permit for {primary_service} in {location}?" if location else f"Do I Need a Permit for {primary_service}?",
        'target_keyword': f"permit {primary_service.lower()} {city.lower()}".strip(),
        'content_type':   'faq',
        'word_count':     700,
        'supports_page':  page.title,
        'supports_url':   page.url,
        'rationale':      "Permit and licensing questions are common, low-competition, and signal professional expertise to both Google and AI systems.",
    })

    return topics[:5]


def _extract_primary_topic(title: str) -> str:
    """Pull a usable topic noun from a page title."""
    if not title:
        return 'service'
    # Remove location modifiers and common suffixes
    cleaned = re.sub(r'\b(ks|mo|tx|fl|ca|ny|il|oh|ga|nc|wa|or|co|az|nv|ut|id|mt|wy|nd|sd|ne|mn|ia|wi|mi|in|oh|pa|ny|nj|ct|ma|ri|nh|vt|me|de|md|va|wv|ky|tn|al|ms|ar|la|ok|nm|ak|hi)\b', '', title, flags=re.IGNORECASE)
    cleaned = re.sub(r'\|.*$', '', cleaned).strip()
    return cleaned[:60] if cleaned else 'service'


def _problem_hook(service: str) -> str:
    """Generate a problem-aware hook for a service type."""
    service_lower = service.lower()
    hooks = {
        'electrician': 'Breaker Keeps Tripping',
        'electric': 'Breaker Keeps Tripping',
        'plumber': 'Water Heater Not Working',
        'plumbing': 'Pipe Burst or Leaking',
        'hvac': 'AC Not Cooling Your Home',
        'roofing': 'Roof Leak After Rain',
        'roofer': 'Roof Leak After Rain',
        'dentist': 'Tooth Pain That Won't Go Away',
        'dental': 'Tooth Pain That Won't Go Away',
    }
    for keyword, hook in hooks.items():
        if keyword in service_lower:
            return hook
    return f"{service} Problem"


def _business_type_label(services: list) -> str:
    """Return a short business type label for comparison articles."""
    if not services:
        return 'Professional'
    service = services[0].lower()
    labels = {
        'electrician': 'Electrician', 'electric': 'Electrician',
        'plumber': 'Plumber', 'plumbing': 'Plumber',
        'hvac': 'HVAC Tech', 'roofer': 'Roofer', 'roofing': 'Roofer',
        'dentist': 'Dentist', 'dental': 'Dentist',
    }
    for k, v in labels.items():
        if k in service:
            return v
    return 'Professional'


# =============================================================================
# ABOUT US INTELLIGENCE (Section 05)
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def about_us_analysis(request, site_id: int, page_id: int):
    """
    GET /api/v1/sites/{site_id}/pages/{page_id}/about-analysis/

    Analyzes an About Us page for E-E-A-T signals:
    - Team member mentions
    - Social/LinkedIn profile links
    - Missing team content flags
    - Generated About Us outline from entity profile

    Only meaningful for pages where URL or title contains 'about'.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    page = get_object_or_404(Page, id=page_id, site=site)

    # Check it's actually an about page
    is_about_page = (
        'about' in page.url.lower() or
        'about' in page.title.lower() or
        'team' in page.url.lower()
    )

    if not is_about_page:
        return Response({
            'is_about_page': False,
            'message': 'This page does not appear to be an About Us or Team page. About analysis is only available for pages with "about" or "team" in their URL or title.',
        }, status=status.HTTP_200_OK)

    content = page.content or ''

    # ── 1. Team member detection ──────────────────────────────────────────────
    team_mentions = _detect_team_members(content)
    social_links  = _detect_social_profile_links(content)

    has_team_members = len(team_mentions) > 0
    has_social_links  = len(social_links) > 0

    # ── 2. Flag missing E-E-A-T signals ──────────────────────────────────────
    flags = []
    recommendations = []

    if not has_team_members:
        flags.append({
            'type':     'missing_team_content',
            'severity': 'high',
            'message':  'No team members mentioned on this page.',
            'why_it_matters': (
                'Google and AI systems (ChatGPT, Gemini, Perplexity) look for real, '
                'verifiable people behind businesses to establish expertise and authority (E-E-A-T). '
                'An About page with no named team members is a missed opportunity to build trust '
                'with both search engines and potential customers.'
            ),
        })
        recommendations.append({
            'type':   'add_team_members',
            'action': 'Add at least the business owner or founder by name, title, and a brief bio.',
            'copy_suggestion': (
                'Adding your name and photo to your About page signals real expertise to Google '
                'and AI systems. Even a two-sentence bio with your years of experience helps.'
            ),
        })

    elif has_team_members and not has_social_links:
        flags.append({
            'type':     'missing_profile_links',
            'severity': 'medium',
            'message':  f"{len(team_mentions)} team member(s) mentioned but no LinkedIn/social profile links found.",
            'why_it_matters': (
                'Team members are mentioned but there are no links to verifiable professional profiles. '
                'Adding LinkedIn profiles for your team is strongly recommended. '
                'Google and AI systems use these to verify the expertise and authority of your business.'
            ),
        })
        recommendations.append({
            'type':   'add_profile_links',
            'action': 'Add LinkedIn profile links for each named team member.',
            'copy_suggestion': (
                'Adding LinkedIn profiles for your team is strongly recommended. '
                'Google and AI systems use these to verify the expertise and authority '
                'of your business. This is optional but highly beneficial.'
            ),
        })

    # ── 3. Entity profile for outline generation ──────────────────────────────
    try:
        profile = SiteEntityProfile.objects.get(site=site)
    except SiteEntityProfile.DoesNotExist:
        profile = None

    about_outline = _generate_about_outline(profile, site) if profile else None

    return Response({
        'is_about_page':      True,
        'page_url':           page.url,
        'page_title':         page.title,
        'has_team_members':   has_team_members,
        'team_mentions':      team_mentions,
        'has_social_links':   has_social_links,
        'social_links_found': social_links,
        'flags':              flags,
        'recommendations':    recommendations,
        'eeeat_score': _calculate_eeat_score(has_team_members, has_social_links, content, profile),
        'about_outline':      about_outline,
    })


def _detect_team_members(content: str) -> list:
    """
    Heuristic detection of named individuals in page content.
    Looks for patterns like: 'Name, Title' or 'Name is a/the ...'
    """
    if not content:
        return []

    # Strip HTML tags for text analysis
    text = re.sub(r'<[^>]+>', ' ', content)
    text = re.sub(r'\s+', ' ', text).strip()

    mentions = []

    # Pattern: capitalized Name + common title words
    title_words = r'(owner|founder|president|ceo|director|manager|technician|specialist|lead|senior|licensed|certified|master)'
    pattern = rf'\b([A-Z][a-z]+ [A-Z][a-z]+)\b(?:[,\s]+(?:is\s+(?:a\s+|the\s+)?|our\s+)?{title_words})?'

    for match in re.finditer(pattern, text, re.IGNORECASE):
        name = match.group(1)
        # Filter out common false positives
        skip = {'Google Business', 'United States', 'Better Business', 'Phone Number',
                'Contact Us', 'About Us', 'Our Team', 'Our Services', 'Service Area',
                'Business Profile', 'Google Maps', 'Facebook Page'}
        if name not in skip and len(name) > 4:
            mentions.append(name)

    # Deduplicate preserving order
    seen = set()
    unique = []
    for m in mentions:
        if m not in seen:
            seen.add(m)
            unique.append(m)

    return unique[:10]


def _detect_social_profile_links(content: str) -> list:
    """Extract LinkedIn, Facebook, Instagram, Twitter/X profile links from content."""
    if not content:
        return []

    social_patterns = [
        (r'https?://(?:www\.)?linkedin\.com/in/[\w\-]+', 'linkedin'),
        (r'https?://(?:www\.)?linkedin\.com/company/[\w\-]+', 'linkedin_company'),
        (r'https?://(?:www\.)?facebook\.com/[\w\.]+', 'facebook'),
        (r'https?://(?:www\.)?instagram\.com/[\w\.]+', 'instagram'),
        (r'https?://(?:www\.)?twitter\.com/[\w]+', 'twitter'),
        (r'https?://(?:www\.)?x\.com/[\w]+', 'twitter'),
    ]

    found = []
    for pattern, platform in social_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            found.append({'url': match.group(0), 'platform': platform})

    return found


def _calculate_eeat_score(has_team: bool, has_social: bool, content: str, profile) -> dict:
    """
    Simple E-E-A-T signal score (0-100) for the About page.
    """
    score = 0
    signals = []

    if has_team:
        score += 30
        signals.append({'signal': 'Named team members present', 'points': 30, 'status': 'pass'})
    else:
        signals.append({'signal': 'Named team members', 'points': 30, 'status': 'fail', 'action': 'Add team member names and titles'})

    if has_social:
        score += 25
        signals.append({'signal': 'Social/LinkedIn profile links', 'points': 25, 'status': 'pass'})
    else:
        signals.append({'signal': 'Social/LinkedIn profile links', 'points': 25, 'status': 'fail', 'action': 'Link to LinkedIn profiles for named team members'})

    # Check for years in business / founding year
    if re.search(r'\b(founded|established|since|serving|years?)\b', content, re.IGNORECASE):
        score += 15
        signals.append({'signal': 'Business history / founding story', 'points': 15, 'status': 'pass'})
    else:
        signals.append({'signal': 'Business history / founding story', 'points': 15, 'status': 'fail', 'action': 'Add when the business was founded and your story'})

    # Check for certifications/licenses
    if re.search(r'\b(certified|licensed|accredited|insured|bonded|award|member|association)\b', content, re.IGNORECASE):
        score += 15
        signals.append({'signal': 'Certifications or credentials mentioned', 'points': 15, 'status': 'pass'})
    else:
        signals.append({'signal': 'Certifications or credentials', 'points': 15, 'status': 'fail', 'action': 'Add licenses, certifications, or industry memberships'})

    # Check for reviews/ratings mention
    if re.search(r'\b(review|rating|star|customer|client|testimonial)\b', content, re.IGNORECASE):
        score += 15
        signals.append({'signal': 'Customer reviews or trust signals', 'points': 15, 'status': 'pass'})
    else:
        signals.append({'signal': 'Customer reviews or trust signals', 'points': 15, 'status': 'fail', 'action': 'Add star rating, review count, or customer testimonials'})

    return {
        'score': min(100, score),
        'signals': signals,
        'grade': 'A' if score >= 85 else 'B' if score >= 70 else 'C' if score >= 50 else 'D',
    }


def _generate_about_outline(profile, site: Site) -> dict:
    """
    Generate a ready-to-approve About Us content outline from entity profile data.
    """
    business_name  = getattr(profile, 'business_name', '') or site.name
    founding_year  = getattr(profile, 'founding_year', None)
    city           = getattr(profile, 'city', '') or ''
    state          = getattr(profile, 'state', '') or ''
    services       = getattr(profile, 'categories', []) or []
    certifications = getattr(profile, 'certifications', []) or []
    team_members   = getattr(profile, 'team_members', []) or []
    brands_used    = getattr(profile, 'brands_used', []) or []
    location       = f"{city}, {state}".strip(', ')

    years_in_business = (2026 - founding_year) if founding_year else None

    sections = []

    # Section 1: Who we are
    who_we_are = f"{business_name} is a"
    if years_in_business:
        who_we_are += f" {years_in_business}-year-old"
    if services:
        who_we_are += f" {services[0].lower()} company"
    if location:
        who_we_are += f" serving {location}"
    who_we_are += '.'

    sections.append({
        'heading': f'About {business_name}',
        'suggested_copy': who_we_are,
        'notes': 'Add 2-3 sentences about your mission and what makes you different from competitors.',
    })

    # Section 2: Our team
    if team_members:
        team_copy = 'Meet the team: ' + ', '.join([f"{m.get('name', '')} ({m.get('title', '')})" for m in team_members[:3]])
    else:
        team_copy = '[Add your name, title, and a 2-3 sentence bio here. Include a professional photo.]'

    sections.append({
        'heading': 'Meet Our Team',
        'suggested_copy': team_copy,
        'notes': 'Named individuals with LinkedIn links improve E-E-A-T. Google and AI systems verify real people behind businesses.',
        'action_required': len(team_members) == 0,
    })

    # Section 3: Credentials
    if certifications:
        creds = f"Certifications & Licenses: {', '.join(certifications[:5])}"
    else:
        creds = '[Add your licenses, certifications, insurance, and any industry memberships here.]'

    sections.append({
        'heading': 'Credentials & Certifications',
        'suggested_copy': creds,
        'notes': 'Licenses and certifications build trust and support E-E-A-T signals.',
        'action_required': len(certifications) == 0,
    })

    # Section 4: Brands / products
    if brands_used:
        sections.append({
            'heading': 'Brands We Work With',
            'suggested_copy': f"We install and service: {', '.join(brands_used[:6])}.",
            'notes': 'Brand-specific content builds topical authority and targets high-intent searches.',
        })

    return {
        'business_name': business_name,
        'sections': sections,
        'word_count_target': 400,
        'note': 'This outline is auto-generated from your Business Profile. Approve to generate the full article.',
    }
