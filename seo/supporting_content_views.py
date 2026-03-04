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
from django.utils.text import slugify

from sites.models import Site
from seo.models import Page, InternalLink, SiteEntityProfile
from seo.profile_validators import get_profile_completeness
from integrations.wordpress_webhook import send_webhook_to_wordpress

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# Minimum supporting pages before we flag a money page as under-supported
MIN_SUPPORTING_PAGES = 2

# Money page types that benefit from supporting content
MONEY_PAGE_TYPES = {'money', 'service', 'service_hub', 'location', 'product'}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_draft(request, site_id: int):
    """
    POST /api/v1/sites/{site_id}/pages/create-draft/

    Body:
    {
      "topic_title": "...",
      "page_type": "sub_page" | "blog_post",
      "target_keyword": "...",
      "hub_page_id": 123
    }

    Action:
    - Fire content.create_draft webhook to WP plugin

    Returns:
    - wp_post_id
    - edit_url
    - status
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)

    topic_title = (request.data.get('topic_title') or '').strip()
    page_type = (request.data.get('page_type') or '').strip()
    target_keyword = (request.data.get('target_keyword') or '').strip()
    hub_page_id = request.data.get('hub_page_id')

    if not topic_title:
        return Response({'error': 'topic_title is required'}, status=status.HTTP_400_BAD_REQUEST)
    if page_type not in {'sub_page', 'blog_post'}:
        return Response({'error': 'page_type must be either sub_page or blog_post'}, status=status.HTTP_400_BAD_REQUEST)
    if not target_keyword:
        return Response({'error': 'target_keyword is required'}, status=status.HTTP_400_BAD_REQUEST)

    if page_type == 'sub_page' and not hub_page_id:
        return Response({'error': 'hub_page_id is required for sub_page'}, status=status.HTTP_400_BAD_REQUEST)

    if hub_page_id:
        try:
            hub_page_id = int(hub_page_id)
        except (TypeError, ValueError):
            return Response({'error': 'hub_page_id must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

        hub_exists = Page.objects.filter(id=hub_page_id, site=site).exists()
        if not hub_exists:
            return Response({'error': f'Hub page with ID {hub_page_id} not found'}, status=status.HTTP_404_NOT_FOUND)

    webhook_payload = {
        'topic_title': topic_title,
        'title': topic_title,
        'page_type': page_type,
        'target_keyword': target_keyword,
        'hub_page_id': hub_page_id,
        'slug': slugify(topic_title),
        'status': 'draft',
    }

    wp_result = send_webhook_to_wordpress(site, 'content.create_draft', webhook_payload)
    if not wp_result.get('success'):
        return Response(
            {'error': f"WordPress webhook failed: {wp_result.get('error', 'unknown error')}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    wp_response = wp_result.get('response') or {}
    wp_post_id = wp_response.get('wp_post_id') or wp_response.get('post_id')
    edit_url = wp_response.get('edit_url')
    if not edit_url and wp_post_id:
        edit_url = f"{site.url.rstrip('/')}/wp-admin/post.php?post={wp_post_id}&action=edit"

    return Response(
        {
            'wp_post_id': wp_post_id,
            'edit_url': edit_url,
            'status': wp_response.get('status', 'draft'),
        },
        status=status.HTTP_201_CREATED,
    )


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
        'dentist': "Tooth Pain That Won't Go Away",
        'dental': "Tooth Pain That Won't Go Away",
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


# =============================================================================
# SCHEMA INVENTORY — Section 03
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def schema_inventory(request, site_id: int, analysis_id: int):
    """
    GET /api/v1/sites/{site_id}/pages/analysis/{analysis_id}/schema/

    Returns:
    - existing_schema:  all JSON-LD blocks already present on the page (from analysis)
    - recommended_types: schema types that SHOULD be present (with checkboxes)
    - generated_schema: ready-to-apply schema built from entity profile
    - blocked:          True if profile is incomplete
    - missing_fields:   which profile fields are blocking schema generation
    """
    from seo.models import PageAnalysis
    from seo.page_analysis_views import _get_entity_profile

    site     = get_object_or_404(Site, id=site_id, user=request.user)
    analysis = get_object_or_404(PageAnalysis, id=analysis_id, site=site)

    # ── Profile completeness check ────────────────────────────────────────────
    try:
        profile = SiteEntityProfile.objects.get(site=site)
        completeness = get_profile_completeness(profile)
    except SiteEntityProfile.DoesNotExist:
        profile = None
        completeness = {
            'schema_blocked': True,
            'missing_required': ['business_name', 'phone', 'logo_url'],
            'blocked_features': ['schema_generation'],
        }

    if completeness.get('schema_blocked'):
        return Response({
            'blocked': True,
            'message': 'Complete your Business Profile to enable schema generation.',
            'missing_fields': completeness.get('missing_required', []),
            'profile_url': f'/dashboard/settings/business-profile/',
            'existing_schema':   _parse_existing_schema(analysis),
            'recommended_types': _get_recommended_schema_types(analysis.page_url),
            'generated_schema':  None,
        })

    # ── Existing schema (from analysis wp_meta) ───────────────────────────────
    existing = _parse_existing_schema(analysis)

    # ── Recommended schema types based on page type ───────────────────────────
    recommended = _get_recommended_schema_types(analysis.page_url)

    # ── Generated schema ──────────────────────────────────────────────────────
    generated = analysis.generated_schema or {}
    if not generated.get('json_ld'):
        # Re-generate from entity profile if not already saved
        entity = _get_entity_profile(site)
        wp_meta = analysis.wp_meta or {}
        generated = _build_schema_from_profile(analysis.page_url, entity, wp_meta, analysis)

    return Response({
        'blocked':          False,
        'existing_schema':  existing,
        'recommended_types': recommended,
        'generated_schema': generated,
        'apply_endpoint':   f'/api/v1/sites/{site_id}/pages/analysis/{analysis_id}/apply/',
        'note': 'To apply: approve the schema recommendation in the analysis, then call the apply endpoint.',
    })


def _parse_existing_schema(analysis) -> list:
    """
    Extract schema types already present on the page from the PageAnalysis wp_meta.
    Returns list of {type, json_ld} dicts for display in the UI.
    """
    wp_meta = analysis.wp_meta or {}
    schema_types = wp_meta.get('schema_types', [])
    schema_raw   = wp_meta.get('schema_raw', [])  # list of JSON-LD blocks if plugin sends them

    existing = []

    # If plugin sent raw JSON-LD blocks
    for block in schema_raw:
        if isinstance(block, dict):
            existing.append({
                'type':   block.get('@type', 'Unknown'),
                'json_ld': block,
                'source': 'page',
            })

    # Fallback: just the type names
    if not existing and schema_types:
        for t in schema_types:
            existing.append({
                'type':   t,
                'json_ld': None,
                'source': 'page',
                'note':   'Full markup not available — re-sync page to retrieve JSON-LD.',
            })

    if not existing:
        existing.append({
            'type':   'none',
            'json_ld': None,
            'source': 'page',
            'note':   'No schema markup detected on this page.',
        })

    return existing


def _get_recommended_schema_types(page_url: str) -> list:
    """
    Return schema types that SHOULD be present based on URL patterns.
    Each item includes a 'present' flag (always False here — dashboard fills it in).
    """
    url = page_url.lower()

    types = [
        {
            'type':     'LocalBusiness',
            'priority': 'required',
            'reason':   'Every page on a local business site should include LocalBusiness schema.',
            'present':  False,
        },
    ]

    if any(x in url for x in ['/faq', 'question', 'faq']):
        types.append({
            'type':     'FAQPage',
            'priority': 'high',
            'reason':   'FAQ content triggers rich results in Google Search.',
            'present':  False,
        })

    if any(x in url for x in ['/service', '/services', '/electrician', '/plumber', '/hvac', '/roofing', '/dentist']):
        types.append({
            'type':     'Service',
            'priority': 'high',
            'reason':   'Service pages benefit from Service schema with pricing and area served.',
            'present':  False,
        })

    if any(x in url for x in ['/blog', '/post', '/article', '/news']):
        types.append({
            'type':     'Article',
            'priority': 'recommended',
            'reason':   'Blog posts with Article schema are eligible for Google News features.',
            'present':  False,
        })

    if 'about' in url:
        types.append({
            'type':     'Organization',
            'priority': 'recommended',
            'reason':   'About pages should include Organization schema with team and founding info.',
            'present':  False,
        })

    if 'contact' in url:
        types.append({
            'type':     'ContactPage',
            'priority': 'recommended',
            'reason':   'Contact pages benefit from ContactPage + LocalBusiness schema.',
            'present':  False,
        })

    types.append({
        'type':     'BreadcrumbList',
        'priority': 'recommended',
        'reason':   'Breadcrumbs improve navigation display in search results.',
        'present':  False,
    })

    return types


def _build_schema_from_profile(page_url: str, entity: dict, wp_meta: dict, analysis) -> dict:
    """Thin wrapper to generate schema using the existing analysis engine."""
    try:
        from seo.page_analysis_views import _generate_schema_for_recommendations
        # Pass empty AI result — schema generation works without AI recs
        return _generate_schema_for_recommendations({}, wp_meta, page_url, site=analysis.site)
    except Exception as e:
        logger.warning('Schema generation failed: %s', e)
        return {}


# =============================================================================
# ARTICLE GENERATION — Section 02 Step 3
# =============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_supporting_article(request, site_id: int, page_id: int):
    """
    Generate a full supporting article from an approved topic plan item.

    POST /api/v1/sites/{site_id}/pages/{page_id}/supporting-content/generate/
    Body:
    {
        "topic": {
            "title": "Generac Generator Installation in Olathe KS — What to Expect",
            "target_keyword": "generac generator installation olathe ks",
            "content_type": "supporting_article",
            "word_count": 1200,
            "supports_page": "Generator Installation",
            "supports_url": "/services/generator-installation/"
        }
    }

    Returns full article HTML + metadata, ready for the Approvals queue.
    Publishes to WordPress when customer approves via the approvals endpoint.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    page = get_object_or_404(Page, id=page_id, site=site)

    topic = request.data.get('topic')
    if not topic or not isinstance(topic, dict):
        return Response({'error': 'topic object is required'}, status=400)

    title = topic.get('title', '').strip()
    target_keyword = topic.get('target_keyword', '').strip()
    word_count = int(topic.get('word_count', 1000))
    content_type = topic.get('content_type', 'supporting_article')
    supports_url = topic.get('supports_url', page.url)

    if not title:
        return Response({'error': 'topic.title is required'}, status=400)

    # Get business profile for specificity
    profile_data = {}
    try:
        profile = SiteEntityProfile.objects.get(site=site)
        profile_data = {
            'business_name': profile.business_name or site.name,
            'city':          profile.city or '',
            'state':         profile.state or '',
            'phone':         profile.phone or '',
            'services':      profile.categories[:5] if profile.categories else [],
            'brands_used':   getattr(profile, 'brands_used', []) or [],
            'service_cities':profile.service_cities[:5] if profile.service_cities else [],
            'rating':        profile.gbp_star_rating,
            'review_count':  profile.gbp_review_count,
        }
    except Exception:
        profile_data = {'business_name': site.name}

    # Build article generation prompt
    location = f"{profile_data.get('city', '')}, {profile_data.get('state', '')}".strip(', ')
    money_page_url = f"{site.url.rstrip('/')}/{supports_url.lstrip('/')}"
    anchor_text = target_keyword or title[:50]

    prompt = f"""Write a complete, publish-ready supporting article for a local service business website.

ARTICLE DETAILS:
Title: {title}
Target keyword: {target_keyword}
Content type: {content_type}
Target word count: {word_count} words
Tone: Professional, helpful, locally relevant

BUSINESS PROFILE:
Business: {profile_data.get('business_name')}
Location: {location}
Services: {', '.join(profile_data.get('services', []))}
Brands used/sold: {', '.join(profile_data.get('brands_used', [])) or 'Not specified'}
Rating: {profile_data.get('rating', 'N/A')}★ ({profile_data.get('review_count', 0)} reviews)

SUPPORTING CONTENT REQUIREMENTS:
- This article MUST include AT LEAST ONE internal link to the money page it supports:
  URL: {money_page_url}
  Anchor text: "{anchor_text}"
  Placement: within the first 400 words and again near the conclusion
- Include 2-4 H2 headings with secondary keywords
- Include an FAQ section at the end with 3-5 real questions customers ask
  (qualify these for FAQPage schema)
- End with a clear CTA: call {profile_data.get('business_name')} at {profile_data.get('phone', '[phone]')} or link to contact page
- Word count target: {word_count} words
- Do NOT include placeholder text — use the real business name, location, and phone number throughout

SPECIFICITY REQUIREMENT: Every paragraph must be specific to this business, this service, and this location.
Do not write generic content that any competitor could publish.

OUTPUT FORMAT (return as JSON):
{{
  "title": "Article title",
  "slug": "url-friendly-slug",
  "target_keyword": "{target_keyword}",
  "meta_description": "155-char meta description with keyword",
  "content_html": "<full HTML article content — h2s, paragraphs, FAQs, CTA>",
  "word_count": 1150,
  "schema": {{
    "article": true,
    "faq_questions": ["Q1", "Q2", "Q3"]
  }},
  "internal_links": [
    {{"url": "{money_page_url}", "anchor_text": "{anchor_text}", "context": "placement description"}}
  ]
}}"""

    # Call AI
    ai_result = None
    if ANTHROPIC_API_KEY:
        try:
            import anthropic, json
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model='claude-opus-4-6',
                max_tokens=4096,
                messages=[{'role': 'user', 'content': prompt}],
            )
            raw = msg.content[0].text
            # Extract JSON
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                ai_result = json.loads(json_match.group())
        except Exception as exc:
            logger.warning('Article generation AI call failed: %s', exc)

    if not ai_result:
        return Response({'error': 'Article generation failed — AI provider unavailable'}, status=502)

    return Response({
        'article': ai_result,
        'meta': {
            'topic':        topic,
            'supports_url': supports_url,
            'money_page_url': money_page_url,
            'site_id':      site_id,
            'page_id':      page_id,
            'status':       'pending_approval',
            'next_step':    'Approve this article in the Approvals tab to publish it to WordPress.',
        }
    }, status=status.HTTP_201_CREATED)


# =============================================================================
# JUNK PAGE FEED — Section 04 (dashboard-facing endpoint)
# =============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def junk_page_feed(request, site_id: int):
    """
    Return pages flagged as junk by the WordPress plugin scanner.
    The WP plugin's /junk-scan REST endpoint sends results here via webhook.
    This endpoint surfaces them to the dashboard.

    GET /api/v1/sites/{id}/junk-pages/
    Query params:
      action=delete,noindex,review  (comma-separated filter)
      status=pending,dismissed

    The WP plugin syncs junk_flag and junk_action fields onto Page records
    via the standard page sync payload.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)

    action_filter = [a.strip() for a in request.query_params.get('action', '').split(',') if a.strip()]
    status_filter = request.query_params.get('status', 'pending')

    qs = Page.objects.filter(site=site).exclude(junk_action__isnull=True).exclude(junk_action='')

    if action_filter:
        qs = qs.filter(junk_action__in=action_filter)

    pages = qs.values('id', 'url', 'title', 'junk_action', 'junk_reason', 'status', 'page_builder')

    # Group by recommended action
    groups = {'delete': [], 'noindex': [], 'review': []}
    for p in pages:
        action = p.get('junk_action', 'review')
        groups.setdefault(action, []).append({
            'id':           p['id'],
            'url':          p['url'],
            'title':        p['title'] or p['url'],
            'junk_action':  action,
            'junk_reason':  p.get('junk_reason', ''),
            'page_builder': p.get('page_builder', 'unknown'),
        })

    return Response({
        'junk_pages':  [p for group in groups.values() for p in group],
        'groups':      groups,
        'meta': {
            'total':   sum(len(v) for v in groups.values()),
            'delete':  len(groups.get('delete', [])),
            'noindex': len(groups.get('noindex', [])),
            'review':  len(groups.get('review', [])),
        }
    })


# ---------------------------------------------------------------------------
# Image Suggestion (no AI call — fast string construction)
# GET /api/v1/sites/{site_id}/pages/{page_id}/image-suggestion/?topic={title}
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def image_suggestion(request, site_id: int, page_id: int):
    """
    Return a DALL-E prompt + alt text constructed from the topic and site entity profile.
    No external API calls — purely string construction, returns immediately.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)
    topic = request.query_params.get('topic', '').strip()
    if not topic:
        from rest_framework.response import Response
        from rest_framework import status as drf_status
        return Response({'error': 'topic query param is required'}, status=drf_status.HTTP_400_BAD_REQUEST)

    # Pull entity profile for city/state/business context
    try:
        profile = SiteEntityProfile.objects.get(site=site)
        city = profile.city or ''
        state = profile.state or ''
        business_name = profile.business_name or ''
    except SiteEntityProfile.DoesNotExist:
        city = ''
        state = ''
        business_name = ''

    location_str = f"{city} {state}".strip() if (city or state) else ''

    # --- Prompt construction ---
    # Use the topic as the primary subject description.
    # Append location and always-on style suffix.
    style_suffix = "photorealistic, professional, bright natural lighting, Canon DSLR quality"

    if location_str:
        dall_e_prompt = (
            f"Professional scene showing {topic} in {location_str}, "
            f"{style_suffix}"
        )
    else:
        dall_e_prompt = f"Professional scene showing {topic}, {style_suffix}"

    # Alt text: concise, keyword-relevant, factual
    if location_str:
        alt_text = f"{topic} in {location_str}"
    else:
        alt_text = topic

    return Response({
        'topic': topic,
        'dall_e_prompt': dall_e_prompt,
        'alt_text': alt_text,
        'style_guidance': 'photorealistic, professional, bright natural lighting',
        'size': '1792x1024',
    })


# ---------------------------------------------------------------------------
# Image Generation — calls OpenAI DALL-E 3
# POST /api/v1/sites/{site_id}/generate-image/
# Body: { "prompt": "...", "size": "1792x1024" }
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_image(request, site_id: int):
    """
    Call OpenAI DALL-E 3 to generate an image from the supplied prompt.
    Returns the image URL (valid ~60 minutes).
    """
    import os
    from datetime import datetime, timezone, timedelta
    from openai import OpenAI
    from rest_framework.response import Response
    from rest_framework import status as drf_status

    # Validate site ownership
    get_object_or_404(Site, id=site_id, user=request.user)

    prompt = request.data.get('prompt', '').strip()
    size = request.data.get('size', '1792x1024').strip()

    if not prompt:
        return Response({'error': 'prompt is required'}, status=drf_status.HTTP_400_BAD_REQUEST)

    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        return Response(
            {'error': 'Image generation is not configured. OPENAI_API_KEY is not set on this server.'},
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        client = OpenAI(api_key=api_key)
        response = client.images.generate(
            model='dall-e-3',
            prompt=prompt,
            size=size,
            quality='standard',
            n=1,
        )
    except Exception as exc:
        error_str = str(exc)
        # Content policy rejection
        if 'content_policy_violation' in error_str or 'safety system' in error_str.lower():
            return Response(
                {'error': 'Image prompt was rejected by content filter. Try a more specific professional description.'},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        # Generic OpenAI failure
        return Response(
            {'error': f'Image generation failed: {error_str}'},
            status=drf_status.HTTP_502_BAD_GATEWAY,
        )

    image_data = response.data[0]
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=60)

    return Response({
        'image_url': image_data.url,
        'prompt': prompt,
        'size': size,
        'revised_prompt': getattr(image_data, 'revised_prompt', None),
        'expires_at': expires_at.isoformat(),
    })
