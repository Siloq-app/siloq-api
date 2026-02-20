"""
Modifier-Aware Conflict Filtering (Stage 4.5)

Eliminates false positives from cross-category modifier conflicts.
Based on Kyle's spec: "Modifier-Aware Conflict Filtering & Service × Location Architecture"

Key Rule: Pages with modifiers from DIFFERENT categories do not cannibalize each other.
- "fireplace tile installation" (service_type) vs "Overland Park tile installation" (location) = NOT competing
- "fireplace tile installation" vs "kitchen tile installation" = NOT competing (different service values)
- Two pages both targeting "Overland Park tile installation" = TRUE conflict

Modifier Categories:
  location, service_type, audience, material, brand_entity, temporal, intent_qualifier
"""
import re
import os
import json
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# =============================================================================
# US CITIES DATABASE (lightweight bootstrap)
# =============================================================================

# Top ~500 US cities by population + common service area cities
# Format: (city_slug, state_abbr, city_name)
# This is bootstrapped; sites can extend via their service area pages
_US_STATES = {
    'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga',
    'hi', 'id', 'il', 'in', 'ia', 'ks', 'ky', 'la', 'me', 'md',
    'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv', 'nh', 'nj',
    'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc',
    'sd', 'tn', 'tx', 'ut', 'vt', 'va', 'wa', 'wv', 'wi', 'wy',
    'dc',
}

_LOCATION_URL_PATTERNS = [
    r'/service-area[s]?/',
    r'/location[s]?/',
    r'/cit(?:y|ies)/',
    r'/areas?-(?:we|served?)/',
    r'/near-me/',
]

# Matches: "overland-park-ks" (exact slug) or within larger slugs
_LOCATION_SLUG_PATTERN = re.compile(
    r'^([a-z][a-z-]+)-(' + '|'.join(_US_STATES) + r')$'
)
# Matches city-state embedded in larger slugs: "overland-park-ks-tile-installation"
_LOCATION_EMBEDDED_PATTERN = re.compile(
    r'([a-z][a-z-]+)-(' + '|'.join(_US_STATES) + r')-'
)

# Common city names that appear in URLs without state suffix
_COMMON_CITIES = {
    'manhattan', 'brooklyn', 'queens', 'bronx', 'staten-island',
    'harlem', 'soho', 'tribeca', 'midtown', 'downtown',
    'overland-park', 'lees-summit', 'blue-springs', 'kansas-city',
    'independence', 'liberty', 'olathe', 'shawnee', 'leawood',
    'prairie-village', 'raytown', 'grandview', 'belton', 'raymore',
    'lee-s-summit',  # alternate slug
}

# Service type keywords
_SERVICE_TYPE_WORDS = {
    'fireplace', 'kitchen', 'bathroom', 'outdoor', 'indoor',
    'artistic', 'custom', 'decorative', 'standard',
    'floor', 'wall', 'backsplash', 'shower', 'pool',
    'installation', 'repair', 'replacement', 'maintenance',
    'remodel', 'remodeling', 'renovation', 'restoration',
    'commercial', 'residential', 'industrial',
    'basement', 'exterior', 'interior', 'flooring',
    'plumbing', 'electrical', 'hvac', 'roofing', 'siding',
    'painting', 'landscaping', 'fencing', 'concrete', 'drywall',
    'waterproofing', 'insulation', 'demolition', 'cleanup',
    'tile', 'hardwood', 'carpet', 'laminate', 'vinyl',
    'catering', 'photography', 'videography', 'entertainment',
    'planning', 'coordination', 'decoration', 'lighting',
    'rental', 'rentals',
}

# Audience keywords
_AUDIENCE_WORDS = {
    'commercial', 'residential', 'industrial',
    'small-business', 'enterprise', 'homeowner', 'contractor',
    'corporate', 'wedding', 'private', 'public',
}

# Material/product keywords
_MATERIAL_WORDS = {
    'porcelain', 'ceramic', 'marble', 'granite', 'quartz',
    'glass', 'mosaic', 'subway', 'travertine', 'slate',
    'rhinestone', 'glitter', 'bling', 'sublimation', 'sewn',
    'led', 'neon', 'inflatable', 'fiberglass', 'wooden',
    'vinyl', 'laminate', 'hardwood', 'bamboo', 'cork',
}

# Temporal keywords
_TEMPORAL_WORDS = {
    'emergency', 'same-day', 'weekend', 'after-hours',
    'next-day', 'rush', '24-hour', '24hr',
}
_TEMPORAL_WORDS.update(str(y) for y in range(2020, 2035))

# Intent qualifier keywords
_INTENT_QUALIFIER_WORDS = {
    'cost', 'price', 'pricing', 'how-to', 'guide', 'tips',
    'vs', 'versus', 'compare', 'comparison', 'review', 'reviews',
    'best', 'top', 'near-me', 'diy', 'ideas', 'inspiration',
    'questions', 'faq', 'checklist',
}


# =============================================================================
# MODIFIER EXTRACTION
# =============================================================================

def extract_modifiers(url: str, title: str = '', site_locations: Set[str] = None) -> List[Dict[str, Any]]:
    """
    Extract modifier categories from a page's URL and title.

    Returns list of modifier dicts: {category, value, confidence, source}
    """
    if not url:
        return []

    modifiers = []
    path = urlparse(url).path.lower().strip('/')
    slug_parts = [p for p in path.split('/') if p]
    all_parts = set()
    for part in slug_parts:
        all_parts.update(part.split('-'))

    title_lower = (title or '').lower()
    title_words = set(re.split(r'[\s\-–—|:,./]+', title_lower))

    # ── LOCATION DETECTION ──
    location_detected = False

    # 1. URL folder pattern (/service-area/, /locations/, etc.)
    for pattern in _LOCATION_URL_PATTERNS:
        if re.search(pattern, '/' + path + '/'):
            location_detected = True
            # Extract city from the path after the location folder
            for i, part in enumerate(slug_parts):
                if re.search(r'service-area|location|cities|areas', part):
                    # City is usually the LAST segment (or next segment if service is in between)
                    remaining = slug_parts[i+1:]
                    if remaining:
                        city_slug = remaining[-1]  # last part = city
                        modifiers.append({
                            'category': 'location',
                            'value': city_slug.replace('-', ' '),
                            'confidence': 0.95,
                            'source': 'url_folder',
                        })
            break

    # 2. City-state slug pattern (overland-park-ks, lees-summit-mo)
    if not location_detected:
        for part in slug_parts:
            # Exact match: "overland-park-ks"
            m = _LOCATION_SLUG_PATTERN.match(part)
            if m:
                city_slug = m.group(1)
                state = m.group(2)
                modifiers.append({
                    'category': 'location',
                    'value': city_slug.replace('-', ' '),
                    'state': state,
                    'confidence': 0.95,
                    'source': 'city_state_slug',
                })
                location_detected = True
                break
            # Embedded match: "overland-park-ks-tile-installation"
            m = _LOCATION_EMBEDDED_PATTERN.match(part)
            if m:
                city_slug = m.group(1)
                state = m.group(2)
                modifiers.append({
                    'category': 'location',
                    'value': city_slug.replace('-', ' '),
                    'state': state,
                    'confidence': 0.90,
                    'source': 'city_state_embedded',
                })
                location_detected = True
                break

    # 3. Known city names in URL
    if not location_detected and site_locations:
        for loc in site_locations:
            loc_slug = loc.lower().replace(' ', '-')
            if loc_slug in slug_parts or loc_slug in path:
                modifiers.append({
                    'category': 'location',
                    'value': loc,
                    'confidence': 0.85,
                    'source': 'site_locations',
                })
                location_detected = True
                break

    # 4. Common city names (exact slug part OR prefix of slug part)
    if not location_detected:
        for part in slug_parts:
            if part in _COMMON_CITIES:
                modifiers.append({
                    'category': 'location',
                    'value': part.replace('-', ' '),
                    'confidence': 0.80,
                    'source': 'common_cities',
                })
                location_detected = True
                break
            # Check if city name is a prefix: "lees-summit-tile-installation"
            for city in sorted(_COMMON_CITIES, key=len, reverse=True):
                if part.startswith(city + '-') and part != city:
                    modifiers.append({
                        'category': 'location',
                        'value': city.replace('-', ' '),
                        'confidence': 0.75,
                        'source': 'common_cities_prefix',
                    })
                    location_detected = True
                    break
            if location_detected:
                break

    # ── SERVICE TYPE DETECTION ──
    service_detected = False

    # URL starts with /services/ or /service/
    if slug_parts and slug_parts[0] in ('services', 'service', 'event-services'):
        service_value_parts = slug_parts[1:] if len(slug_parts) > 1 else slug_parts
        service_value = ' '.join(p.replace('-', ' ') for p in service_value_parts)
        modifiers.append({
            'category': 'service_type',
            'value': service_value,
            'confidence': 0.95,
            'source': 'url_folder',
        })
        service_detected = True

    # Service-type words in URL (only if not already detected via folder)
    if not service_detected:
        matched_service = all_parts & _SERVICE_TYPE_WORDS
        if len(matched_service) >= 1:
            modifiers.append({
                'category': 'service_type',
                'value': ' '.join(sorted(matched_service)),
                'confidence': 0.75,
                'source': 'keyword_match',
            })

    # ── AUDIENCE DETECTION ──
    matched_audience = all_parts & _AUDIENCE_WORDS
    if matched_audience:
        modifiers.append({
            'category': 'audience',
            'value': ' '.join(sorted(matched_audience)),
            'confidence': 0.85,
            'source': 'keyword_match',
        })

    # ── MATERIAL DETECTION ──
    matched_material = (all_parts | title_words) & _MATERIAL_WORDS
    if matched_material:
        modifiers.append({
            'category': 'material',
            'value': ' '.join(sorted(matched_material)),
            'confidence': 0.80,
            'source': 'keyword_match',
        })

    # ── TEMPORAL DETECTION ──
    matched_temporal = all_parts & _TEMPORAL_WORDS
    if matched_temporal:
        modifiers.append({
            'category': 'temporal',
            'value': ' '.join(sorted(matched_temporal)),
            'confidence': 0.80,
            'source': 'keyword_match',
        })

    # ── INTENT QUALIFIER DETECTION ──
    matched_intent = all_parts & _INTENT_QUALIFIER_WORDS
    if matched_intent:
        modifiers.append({
            'category': 'intent_qualifier',
            'value': ' '.join(sorted(matched_intent)),
            'confidence': 0.80,
            'source': 'keyword_match',
        })

    return modifiers


def get_primary_modifier_category(modifiers: List[Dict]) -> str:
    """
    Get the primary (highest-priority) modifier category.
    Priority: location > service_type > audience > material > brand_entity > temporal > intent_qualifier
    """
    if not modifiers:
        return 'none'

    priority = ['location', 'service_type', 'audience', 'material',
                'brand_entity', 'temporal', 'intent_qualifier']

    for cat in priority:
        if any(m['category'] == cat for m in modifiers):
            return cat

    return 'unknown'


def get_modifier_value(modifiers: List[Dict], category: str) -> str:
    """Get the value for a specific modifier category."""
    for m in modifiers:
        if m['category'] == category:
            return m.get('value', '')
    return ''


# =============================================================================
# CROSS-CATEGORY CONFLICT FILTER
# =============================================================================

def classify_conflict_by_modifiers(
    competing_pages: List[Dict],
    site_locations: Set[str] = None,
) -> Dict[str, Any]:
    """
    Classify a conflict using modifier-aware analysis.

    Args:
        competing_pages: List of dicts with 'url', 'title', 'page_type' keys
        site_locations: Optional set of known city names for the site

    Returns:
        {
            'verdict': 'TRUE_CONFLICT' | 'FALSE_POSITIVE' | 'REVIEW' | 'SCORING_NEEDED',
            'reason': str,
            'modifier_categories': list of unique categories,
            'cross_category': bool,
            'page_modifiers': list of modifier data per page,
        }
    """
    page_modifier_data = []

    for page in competing_pages:
        url = page.get('url', '')
        title = page.get('title', '')
        mods = extract_modifiers(url, title, site_locations)
        primary = get_primary_modifier_category(mods)
        primary_value = get_modifier_value(mods, primary) if primary != 'none' else ''

        page_modifier_data.append({
            'url': url,
            'modifiers': mods,
            'primary_category': primary,
            'primary_value': primary_value,
        })

    categories = [pm['primary_category'] for pm in page_modifier_data]
    unique_categories = list(set(categories))

    result = {
        'page_modifiers': page_modifier_data,
        'modifier_categories': unique_categories,
        'cross_category': False,
    }

    # ── RULE 1: All pages same modifier category ──
    if len(unique_categories) == 1 and unique_categories[0] != 'none':
        cat = unique_categories[0]
        values = [pm['primary_value'] for pm in page_modifier_data]
        unique_values = list(set(v for v in values if v))

        if len(unique_values) <= 1 and unique_values:
            # SAME category AND same value = true cannibalization
            result['verdict'] = 'TRUE_CONFLICT'
            result['reason'] = f'Both pages target {cat}: "{unique_values[0]}"'
        else:
            # Same category, different values = legitimate differentiation
            result['verdict'] = 'FALSE_POSITIVE'
            result['reason'] = (
                f'Different {cat} values: {" vs ".join(unique_values[:5])}. '
                f'Legitimate differentiation, not competition.'
            )
        return result

    # ── RULE 2: Pages have DIFFERENT modifier categories ──
    non_none = [c for c in unique_categories if c != 'none']
    if len(non_none) > 1:
        result['verdict'] = 'FALSE_POSITIVE'
        result['cross_category'] = True
        result['reason'] = (
            f'Cross-category: {" vs ".join(non_none)}. '
            f'Different intent types do not compete.'
        )
        return result

    # ── RULE 3: One or more pages have no modifier (root keyword) ──
    if 'none' in unique_categories:
        # If mix of none + categorized, the root page may compete with all
        if len(non_none) > 0:
            result['verdict'] = 'REVIEW'
            result['reason'] = (
                'One page targets the root keyword without a modifier. '
                'It may compete with all variants. Verify with GSC query data.'
            )
        else:
            # All pages have no modifier = let scoring handle it
            result['verdict'] = 'SCORING_NEEDED'
            result['reason'] = 'No modifiers detected on any page.'
        return result

    # Default
    result['verdict'] = 'SCORING_NEEDED'
    result['reason'] = 'Could not determine modifier relationship.'
    return result


# =============================================================================
# PIPELINE INTEGRATION: Stage 4.5 Filter
# =============================================================================

def filter_conflicts_by_modifiers(
    issues: List[Dict[str, Any]],
    site_locations: Set[str] = None,
) -> List[Dict[str, Any]]:
    """
    Stage 4.5: Filter a list of cannibalization issues using modifier-aware analysis.

    - FALSE_POSITIVE conflicts are downgraded to INFO severity
    - TRUE_CONFLICT conflicts pass through unchanged
    - REVIEW conflicts are capped at MEDIUM severity
    - Adds modifier_verdict and modifier_reason to each issue

    Args:
        issues: List of conflict dicts from detect_static_cannibalization
        site_locations: Optional set of known city names for the site

    Returns:
        Filtered list of issues (false positives kept but downgraded to INFO)
    """
    filtered = []

    for issue in issues:
        competing = issue.get('competing_pages', [])
        if len(competing) < 2:
            filtered.append(issue)
            continue

        verdict = classify_conflict_by_modifiers(competing, site_locations)

        # Annotate the issue
        issue['modifier_verdict'] = verdict['verdict']
        issue['modifier_reason'] = verdict['reason']
        issue['modifier_categories'] = verdict['modifier_categories']
        issue['cross_category'] = verdict.get('cross_category', False)

        if verdict['verdict'] == 'FALSE_POSITIVE':
            # Downgrade to INFO — keep for transparency but not actionable
            issue['severity'] = 'INFO'
            issue['original_severity'] = issue.get('severity', 'MEDIUM')
            issue['explanation'] = (
                verdict['reason'] + ' ' +
                'This is correct site architecture, not cannibalization. '
                'Ensure cross-linking between service and location pages.'
            )
            issue['recommendation'] = (
                'No action needed. These pages serve different search intents. '
                'Cross-link between them for best results.'
            )

        elif verdict['verdict'] == 'REVIEW':
            # Cap at MEDIUM
            severity_rank = {'INFO': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}
            if severity_rank.get(issue.get('severity', 'MEDIUM'), 2) > 2:
                issue['severity'] = 'MEDIUM'
            issue['explanation'] = verdict['reason'] + ' ' + issue.get('explanation', '')

        # TRUE_CONFLICT and SCORING_NEEDED pass through unchanged

        filtered.append(issue)

    return filtered


def bootstrap_site_locations(pages) -> Set[str]:
    """
    Bootstrap a set of known location names from a site's existing pages.
    Scans URL patterns and extracts city names.
    """
    locations = set()

    for page in pages:
        url = getattr(page, 'url', '') or ''
        path = urlparse(url).path.lower().strip('/')
        slug_parts = [p for p in path.split('/') if p]

        # Check for /service-area/<city>/ or /service-area/<service>/<city>/
        for i, part in enumerate(slug_parts):
            if part in ('service-area', 'service-areas', 'locations', 'location'):
                remaining = slug_parts[i+1:]
                if remaining:
                    city_slug = remaining[-1]
                    city_name = city_slug.replace('-', ' ')
                    # Filter out service-like words
                    if city_name not in _SERVICE_TYPE_WORDS:
                        locations.add(city_name)

        # Check for city-state slug pattern anywhere in URL
        for part in slug_parts:
            m = _LOCATION_SLUG_PATTERN.match(part)
            if m:
                locations.add(m.group(1).replace('-', ' '))

    return locations
