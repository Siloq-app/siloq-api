"""
Page Classification Engine — classifies pages into 6 types.

Types: money, supporting, utility, conversion, archive, product

Algorithm:
  Phase 1 — Exclusion checks (instant disqualification by slug/post_type/noindex)
  Phase 2 — Scoring (cross-reference business profile, content depth, URL structure)
"""
import re
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Exclusion pattern sets ──────────────────────────────────

UTILITY_SLUGS = {
    'about', 'about-us', 'our-story', 'our-team', 'meet-the-team', 'meet-our',
    'staff', 'team', 'leadership', 'management',
    'contact', 'contact-us', 'get-in-touch',
    'privacy', 'privacy-policy', 'terms', 'terms-of-service', 'terms-and-conditions',
    'cookie-policy', 'disclaimer',
    'careers', 'jobs', 'employment', 'hiring', 'join-our-team',
    'sitemap', 'site-map', 'login', 'register', 'my-account', 'account', 'dashboard',
    'cart', 'checkout', 'order-confirmation', 'order-tracking', 'wishlist', 'compare',
    'faq', 'faqs', 'help', 'support',
    'testimonials', 'reviews', 'gallery', 'portfolio', 'our-work', 'case-studies',
    'locations', 'find-us', 'directions',
    'thank-you', 'thanks', 'confirmation',
    'search', 'search-results', '404', 'error',
}

CONVERSION_SLUGS = {
    'request-service', 'request-a-quote', 'get-a-quote', 'get-quote',
    'free-quote', 'free-estimate',
    'book-now', 'book-appointment',
    'schedule', 'schedule-appointment', 'schedule-consultation',
    'apply', 'apply-now', 'sign-up', 'subscribe',
    'reservations', 'reserve', 'book-a-table',
    'request-demo', 'free-trial', 'start-free-trial',
}

ARCHIVE_SLUGS = {
    'blog', 'news', 'articles', 'resources', 'category', 'tag', 'author',
    'events', 'press', 'media',
}

TEAM_INDICATORS = {
    'team', 'staff', 'people', 'crew', 'our-', 'meet-', 'bios',
    'about-us', 'who-we-are',
}

UTILITY_TEMPLATES = {
    'template-contact', 'template-about', 'page-contact', 'template-team',
    'template-faq', 'template-fullwidth-form', 'template-landing', 'template-blank',
}


def _get_slug(page):
    """Extract the last path segment from URL or slug field."""
    slug = getattr(page, 'slug', '') or ''
    if slug:
        return slug.lower().strip('/')
    url = getattr(page, 'url', '') or ''
    if url:
        path = urlparse(url).path.strip('/')
        return path.split('/')[-1] if path else ''
    return ''


def _get_path_segments(page):
    """Get URL path segments."""
    url = getattr(page, 'url', '') or ''
    if url:
        path = urlparse(url).path.strip('/')
        return [s for s in path.split('/') if s]
    return []


def _word_count(page):
    """Estimate word count from content."""
    content = getattr(page, 'content', '') or ''
    # Strip HTML tags roughly
    text = re.sub(r'<[^>]+>', ' ', content)
    return len(text.split())


def _has_team_indicator(title, slug):
    """Check if title or slug indicates a team/staff page."""
    combined = f"{title} {slug}".lower()
    for indicator in TEAM_INDICATORS:
        if indicator in combined:
            # More specific check — avoid matching "our-services" etc.
            if indicator in ('our-', 'meet-'):
                # Check what follows
                if re.search(rf'{re.escape(indicator)}(team|staff|people|crew|bios)', combined):
                    return True
            else:
                return True
    return False


# ── Phase 1: Exclusion checks ──────────────────────────────

def _phase1_exclusion(page):
    """
    Instant disqualification checks.
    Returns (page_type, confidence, reason) or None if no exclusion matched.
    """
    slug = _get_slug(page)
    post_type = getattr(page, 'post_type', '') or ''
    title = (getattr(page, 'title', '') or '').lower()

    # WordPress post_type = product → e-commerce product
    if post_type == 'product':
        return ('product', 0.95, 'WordPress post_type is product')

    # Archive post types
    if post_type in ('product_cat', 'category'):
        return ('archive', 0.90, f'WordPress post_type is {post_type}')

    # Noindex → utility
    if getattr(page, 'is_noindex', False):
        return ('utility', 0.90, 'Page is noindex')

    # Slug-based exclusions
    if slug in UTILITY_SLUGS:
        return ('utility', 0.90, f'Slug "{slug}" matches utility pattern')

    if slug in CONVERSION_SLUGS:
        return ('conversion', 0.90, f'Slug "{slug}" matches conversion pattern')

    if slug in ARCHIVE_SLUGS:
        return ('archive', 0.85, f'Slug "{slug}" matches archive pattern')

    # Team/staff indicator
    if _has_team_indicator(title, slug):
        return ('utility', 0.85, 'Title/slug indicates team/staff page')

    # Utility template check (if page has a template attribute)
    template = getattr(page, 'template', '') or ''
    if template.lower() in UTILITY_TEMPLATES:
        return ('utility', 0.85, f'Template "{template}" is a utility template')

    return None


# ── Phase 2: Scoring ────────────────────────────────────────

def _phase2_score(page, business_profile=None):
    """
    Score pages that passed exclusion checks.
    Returns (page_type, confidence, reason).
    """
    post_type = getattr(page, 'post_type', '') or ''
    segments = _get_path_segments(page)
    words = _word_count(page)
    title = (getattr(page, 'title', '') or '').lower()
    slug = _get_slug(page)

    # Blog posts default to supporting
    if post_type == 'post':
        return ('supporting', 0.80, 'Blog post (post_type=post) defaults to supporting')

    # Check URL structure: /blog/anything → supporting
    if segments and segments[0] in ('blog', 'news', 'articles', 'resources'):
        return ('supporting', 0.75, f'URL under /{segments[0]}/ indicates supporting content')

    # Cross-reference with business profile services
    service_match_score = 0.0
    matched_service = None
    if business_profile:
        services = business_profile.get('primary_services', []) or []
        for service in services:
            service_lower = service.lower().strip()
            if not service_lower:
                continue
            # Check title and slug for service keyword match
            service_words = service_lower.split()
            if any(sw in title for sw in service_words) or any(sw in slug for sw in service_words):
                service_match_score = 0.6
                matched_service = service
                # Stronger match if the full service name appears
                if service_lower in title or service_lower.replace(' ', '-') in slug:
                    service_match_score = 0.8
                    break

    # Content depth
    depth_score = 0.0
    if words >= 800:
        depth_score = 0.3
    elif words >= 400:
        depth_score = 0.15

    # URL structure: top-level slug = more likely money page
    url_score = 0.0
    if len(segments) == 1:
        url_score = 0.2
    elif len(segments) == 2 and segments[0] in ('services', 'products', 'solutions'):
        url_score = 0.25

    # Combine scores
    total = service_match_score + depth_score + url_score

    if total >= 0.8:
        reason = f'High money page score ({total:.2f})'
        if matched_service:
            reason += f' — matches service "{matched_service}"'
        return ('money', min(0.95, 0.5 + total * 0.4), reason)

    if total >= 0.5:
        reason = f'Moderate score ({total:.2f})'
        if matched_service:
            reason += f' — partial match with service "{matched_service}"'
        # Could be money or supporting — lean toward supporting (classify DOWN)
        return ('supporting', 0.60, reason + ' — classified as supporting (classify DOWN rule)')

    # Default: supporting
    return ('supporting', 0.70, 'Default classification — no strong signals')


# ── Public API ──────────────────────────────────────────────

def classify_page(page, business_profile=None):
    """
    Classify a page into one of 6 types.

    Returns: {'page_type': str, 'confidence': float, 'reason': str}

    If page.page_type_override is True, return current type unchanged.
    """
    if getattr(page, 'page_type_override', False):
        return {
            'page_type': page.page_type_classification,
            'confidence': 1.0,
            'reason': 'Manual override — not reclassified',
        }

    # Phase 1: exclusion
    result = _phase1_exclusion(page)
    if result:
        page_type, confidence, reason = result
        return {'page_type': page_type, 'confidence': confidence, 'reason': reason}

    # Phase 2: scoring
    page_type, confidence, reason = _phase2_score(page, business_profile)
    return {'page_type': page_type, 'confidence': confidence, 'reason': reason}


def classify_and_save(page, business_profile=None):
    """Classify a page and persist the result. Returns the classification dict."""
    result = classify_page(page, business_profile=business_profile)
    if not getattr(page, 'page_type_override', False):
        page.page_type_classification = result['page_type']
        page.is_money_page = (result['page_type'] == 'money')
        page.save(update_fields=['page_type_classification', 'is_money_page'])
    return result


def _get_business_profile(site):
    """Extract business profile dict from a Site object."""
    return {
        'primary_services': site.primary_services or [],
        'service_areas': site.service_areas or [],
        'business_type': site.business_type or '',
        'business_description': site.business_description or '',
    }


def classify_all_pages(site_id):
    """
    Re-classify all pages for a site.
    Skip pages with page_type_override=True.
    Returns list of classification results.
    """
    from sites.models import Site
    from seo.models import Page

    site = Site.objects.get(id=site_id)
    profile = _get_business_profile(site)
    pages = Page.objects.filter(site=site, page_type_override=False)

    results = []
    for page in pages.iterator():
        result = classify_page(page, business_profile=profile)
        page.page_type_classification = result['page_type']
        page.is_money_page = (result['page_type'] == 'money')
        page.save(update_fields=['page_type_classification', 'is_money_page'])
        results.append({'page_id': page.id, **result})

    logger.info(f"Classified {len(results)} pages for site {site_id}")
    return results
