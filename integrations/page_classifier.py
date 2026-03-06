"""
Page Role Classification — Hub / Spoke / Supporting / Orphan

Classifies pages based on URL structure, child page count, and inbound links.
This is separate from the 6-type page_type_classification (money/supporting/utility/etc).
"""
import re
import logging
from urllib.parse import urlparse

from seo.models import Page, InternalLink

logger = logging.getLogger(__name__)

HUB_URL_PATTERNS = {
    '/services/', '/service-areas/', '/areas-we-serve/', '/locations/',
}

SERVICE_KEYWORDS = {
    'panel', 'wiring', 'electrical', 'ev-charging', 'generator', 'breaker',
    'outlet', 'circuit', 'plumbing', 'hvac', 'roofing', 'remodel',
    'installation', 'repair', 'maintenance', 'inspection', 'upgrade',
}

SKIP_SLUGS = {'', 'home', 'contact', 'about', 'about-us', 'privacy',
              'privacy-policy', 'terms', 'terms-of-service'}


def _get_path(page):
    url = getattr(page, 'url', '') or ''
    if url:
        return urlparse(url).path.lower().rstrip('/') + '/'
    return '/'


def _is_city_pattern(path):
    """Check if a URL path contains a city/location-like slug segment."""
    segments = [s for s in path.strip('/').split('/') if s]
    if not segments:
        return False
    for seg in segments:
        # Location pages often have city names as slugs (e.g. /olathe/, /bonner-springs/)
        # Heuristic: not a service keyword, single word or hyphenated, length 3+
        if seg not in SERVICE_KEYWORDS and len(seg) >= 3 and not seg.isdigit():
            # Check if it's under a hub path
            if any(hub.strip('/') in path for hub in HUB_URL_PATTERNS):
                return True
    return False


def classify_page_role(page):
    """
    Classify a page's structural role.

    Returns: 'hub', 'spoke', 'supporting', or 'orphan'
    """
    path = _get_path(page)
    slug = path.strip('/').split('/')[-1] if path.strip('/') else ''

    # Rule 1: Exact hub URL patterns
    if path in HUB_URL_PATTERNS:
        return 'hub'

    # Rule 2: Page has 3+ child pages
    child_count = Page.objects.filter(parent_id=page.id, site=page.site).count()
    if child_count >= 3:
        return 'hub'

    # Check if site has any hub pages (needed for spoke classification)
    site_has_hub = Page.objects.filter(
        site=page.site,
        url__regex=r'/(services|service-areas|areas-we-serve|locations)/$'
    ).exists()

    # Rule 3: City/location pattern + site has a hub
    if site_has_hub and _is_city_pattern(path):
        return 'spoke'

    # Rule 4: Service-specific keywords but not the main services page
    path_segments = set(re.split(r'[/\-_]', path.strip('/')))
    if path_segments & SERVICE_KEYWORDS and slug not in ('services', 'our-services'):
        return 'supporting'

    # Rule 5: Orphan — no inbound links and not a utility page
    if slug not in SKIP_SLUGS:
        has_inbound = InternalLink.objects.filter(
            target_page=page, site=page.site
        ).exists()
        is_homepage = getattr(page, 'is_homepage', False)
        if not has_inbound and not is_homepage:
            return 'orphan'

    # Fallback
    return 'supporting'


def classify_all_pages_roles(site):
    """
    Classify all pages in a site. Respects page_type_override.
    Returns list of dicts with page_id and role.
    """
    pages = Page.objects.filter(site=site, status='publish')
    results = []
    for page in pages.iterator():
        role = classify_page_role(page)
        if not getattr(page, 'page_type_override', False):
            page.page_role = role
            # Store in analysis_data via PageAnalysis if available, or just track
        results.append({'page_id': page.id, 'url': page.url, 'role': role})
    logger.info("Classified %d page roles for site %s", len(results), site.id)
    return results
