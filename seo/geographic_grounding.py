"""
Geographic Ghosting Detection & Informational Gain Scoring
==========================================================
Detects when a location page lacks GBP grounding signals (Geographic Ghosting)
and scores how much unique informational value a page adds vs. other pages in
the same hub (Informational Gain).

No migrations required — uses existing Site and SiteEntityProfile fields.
"""

import re
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

US_STATES = {
    'al','ak','az','ar','ca','co','ct','de','fl','ga','hi','id','il','in','ia',
    'ks','ky','la','me','md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj',
    'nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt',
    'va','wa','wv','wi','wy',
}

STOP_WORDS = {
    'a','an','the','and','or','but','in','on','at','to','for','of','with','by',
    'from','is','are','was','were','be','been','have','has','had','do','does',
    'did','will','would','could','should','may','might','can','our','we','you',
    'your','us','that','this','it','its','they','their','not','no',
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _normalize_area(area):
    return re.sub(r'[^a-z0-9]', '-', area.lower()).strip('-')

def _area_in_slug(area, slug):
    slug_lower = slug.lower()
    if _normalize_area(area) in slug_lower:
        return True
    first = area.split()[0].lower()
    return len(first) > 3 and first in slug_lower

def _area_in_text(area, text):
    if not text:
        return False
    text_lower = text.lower()
    area_lower = area.lower()
    area_base = re.split(r'[,\s]+(?:' + '|'.join(US_STATES) + r')\b', area_lower)[0].strip()
    return area_lower in text_lower or (len(area_base) > 3 and area_base in text_lower)

def _gbp_has_data(site):
    return bool(getattr(site, 'gbp_url', None) or getattr(site, 'gbp_website', None) or getattr(site, 'gbp_place_id', None))

def _gbp_domain_matches_site(site):
    gbp_website = getattr(site, 'gbp_website', '') or ''
    site_url = getattr(site, 'url', '') or ''
    if not gbp_website or not site_url:
        return False
    try:
        return urlparse(gbp_website).netloc.replace('www.','') == urlparse(site_url).netloc.replace('www.','')
    except Exception:
        return False

def _gbp_covers_location(site, target_location):
    service_areas = getattr(site, 'service_areas', None) or []
    if not service_areas or not target_location:
        return False
    target_lower = target_location.lower()
    for area in service_areas:
        area_lower = (area or '').lower()
        if target_lower in area_lower or area_lower in target_lower:
            return True
        t0 = target_lower.split()[0] if target_lower.split() else ''
        a0 = area_lower.split()[0] if area_lower.split() else ''
        if len(t0) > 3 and t0 == a0:
            return True
    return False

def _reviews_mention_location(entity_profile, target_location):
    if not entity_profile or not target_location:
        return False
    reviews = getattr(entity_profile, 'gbp_reviews', None) or []
    target_lower = target_location.lower().split(',')[0].strip()
    if len(target_lower) < 3:
        return False
    for review in reviews:
        text = ''
        if isinstance(review, dict):
            text = review.get('text','') or review.get('comment','') or ''
        if target_lower in text.lower():
            return True
    return False


# ── Geographic Ghosting ───────────────────────────────────────────────────────

GROUNDING_UNKNOWN = 'unknown'
GROUNDING_NONE    = 'none'
GROUNDING_WEAK    = 'weak'
GROUNDING_STRONG  = 'strong'


def detect_location_page(page, h1_text=''):
    site = page.site
    service_areas = getattr(site, 'service_areas', None) or []
    slug  = (page.slug or '').lower()
    url   = (page.url or '').lower()
    title = (page.title or '').lower()
    combined = f"{slug} {url} {title} {h1_text}".lower()

    for area in service_areas:
        if not area:
            continue
        if _area_in_slug(area, slug) or _area_in_text(area, combined):
            return True, area

    # Fallback slug pattern
    if re.search(r'(?:in|near|around|serving)\b', slug):
        parts = re.split(r'[-/]', slug)
        for part in parts:
            if len(part) > 3 and part not in US_STATES and not part.isdigit():
                return True, part.replace('-',' ').title()

    return False, None


def compute_geographic_grounding(page, h1_text=''):
    is_location, target_location = detect_location_page(page, h1_text)

    if not is_location:
        return {
            'is_location_page': False, 'target_location': None,
            'grounding_status': None, 'grounding_signals': [],
            'missing_signals': [], 'warning': False,
            'warning_message': None, 'recommendations': [],
        }

    site = page.site
    entity_profile = getattr(site, 'entity_profile', None)
    all_signal_names = [
        'gbp_domain_matches',
        'gbp_service_area_covers_location',
        'gbp_reviews_mention_location',
    ]

    if not _gbp_has_data(site):
        return {
            'is_location_page': True, 'target_location': target_location,
            'grounding_status': GROUNDING_UNKNOWN,
            'grounding_signals': [], 'missing_signals': all_signal_names,
            'warning': True,
            'warning_message': (
                f'This page targets "{target_location}" but no Google Business Profile is '
                f'connected. Without GBP grounding, Google may classify this as Geographically '
                f'Ghosting and suppress it.'
            ),
            'recommendations': [
                'Connect your Google Business Profile in Siloq Settings to enable geographic grounding checks.',
                f'Ensure your GBP listing covers "{target_location}" in its service areas.',
                'Encourage customers in this area to leave reviews mentioning the location.',
            ],
        }

    checks = {
        'gbp_domain_matches':               _gbp_domain_matches_site(site),
        'gbp_service_area_covers_location': _gbp_covers_location(site, target_location),
        'gbp_reviews_mention_location':     _reviews_mention_location(entity_profile, target_location),
    }

    signals_found   = [k for k, v in checks.items() if v]
    signals_missing = [k for k, v in checks.items() if not v]
    count = len(signals_found)

    if count >= 2:
        status = GROUNDING_STRONG
    elif count == 1:
        status = GROUNDING_WEAK
    else:
        status = GROUNDING_NONE

    warning = status in (GROUNDING_NONE, GROUNDING_WEAK)
    warning_message = None
    recs = []

    if warning:
        adj = 'limited' if status == GROUNDING_WEAK else 'no'
        warning_message = (
            f'This page targets "{target_location}" but has {adj} GBP grounding signals. '
            f'Google may classify this as Geographically Ghosting and suppress the page.'
        )
        if 'gbp_service_area_covers_location' in signals_missing:
            recs.append(f'Add "{target_location}" to your Google Business Profile service areas.')
        if 'gbp_reviews_mention_location' in signals_missing:
            city = target_location.split(',')[0]
            recs.append(f'Encourage customers in {city} to leave reviews mentioning the area.')
        if 'gbp_domain_matches' in signals_missing:
            recs.append('Ensure your GBP listing website URL points to this site\'s domain.')
        city = target_location.split(',')[0]
        recs.append(f'Add your business to local directories (Yelp, BBB, Chamber) for {city}.')

    return {
        'is_location_page': True,
        'target_location': target_location,
        'grounding_status': status,
        'grounding_signals': signals_found,
        'missing_signals': signals_missing,
        'warning': warning,
        'warning_message': warning_message,
        'recommendations': recs,
    }


# ── Informational Gain ────────────────────────────────────────────────────────

def _tokenize(text):
    tokens = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return [t for t in tokens if t not in STOP_WORDS]

def _strip_location_tokens(text, service_areas):
    result = text
    for area in (service_areas or []):
        if not area:
            continue
        for part in re.split(r'[\s,]+', area):
            if len(part) > 2:
                result = re.sub(r'\b' + re.escape(part) + r'\b', '', result, flags=re.IGNORECASE)
    return result

def _shingle(tokens, size=4):
    if len(tokens) < size:
        return {tuple(tokens)}
    return {tuple(tokens[i:i+size]) for i in range(len(tokens) - size + 1)}

def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def compute_informational_gain(page, page_content, hub_pages_content):
    if not page_content:
        return _ig_result(0.0, [], 'No content available to score.')

    service_areas = getattr(page.site, 'service_areas', None) or [] if page.site else []

    norm_page = _strip_location_tokens(page_content, service_areas)
    page_shingles = _shingle(_tokenize(norm_page))

    if not hub_pages_content:
        return _ig_result(1.0, [], None)

    similarities = []
    for other in hub_pages_content:
        if not other:
            continue
        norm_other = _strip_location_tokens(other, service_areas)
        sim = _jaccard(page_shingles, _shingle(_tokenize(norm_other)))
        similarities.append(sim)

    if not similarities:
        return _ig_result(1.0, [], None)

    avg_sim = sum(similarities) / len(similarities)
    max_sim = max(similarities)
    combined_sim = avg_sim * 0.6 + max_sim * 0.4
    unique_ratio = 1.0 - combined_sim
    swap_detected = max_sim > 0.75 and unique_ratio < 0.35

    return _ig_result(
        unique_ratio,
        _ig_recommendations(page, unique_ratio, swap_detected),
        None, avg_sim, max_sim, swap_detected,
    )


def _ig_result(unique_ratio, recommendations, note=None,
               avg_similarity=None, max_similarity=None, swap_pattern_detected=False):
    if unique_ratio >= 0.50:
        label, emoji = 'strong', '✅'
    elif unique_ratio >= 0.31:
        label, emoji = 'moderate', '🟢'
    elif unique_ratio >= 0.15:
        label, emoji = 'weak', '🟡'
    else:
        label, emoji = 'none', '🔴'

    result = {
        'unique_ratio': round(unique_ratio, 3),
        'unique_percentage': round(unique_ratio * 100, 1),
        'label': label,
        'emoji': emoji,
        'warning': label in ('weak', 'none'),
        'swap_pattern_detected': swap_pattern_detected,
        'recommendations': recommendations,
    }
    if avg_similarity is not None:
        result['avg_similarity_to_hub'] = round(avg_similarity, 3)
    if max_similarity is not None:
        result['max_similarity_to_hub'] = round(max_similarity, 3)
    if note:
        result['note'] = note
    return result


def _ig_recommendations(page, unique_ratio, swap_detected):
    recs = []
    if swap_detected:
        recs.append(
            "This page appears to be a city-swap of another page. Google's Scaled Content "
            "classifier will suppress both pages. Add location-specific content that cannot "
            "be replicated by simply replacing the city name."
        )
    if unique_ratio < 0.30:
        recs.append(
            "Add local specificity: reference area landmarks, neighborhoods, local regulations, "
            "or area-specific conditions unique to this location."
        )
        recs.append(
            "Include a real case study, project example, or customer story from this specific area."
        )
    if unique_ratio < 0.50:
        recs.append(
            "Add data unique to this area: local statistics, service pricing specific to this "
            "market, or community context."
        )
    return recs
