"""
Utility functions for cannibalization detection.
URL normalization, slug comparison, geographic extraction, etc.
"""
import re
from typing import Set, Optional, Tuple
from urllib.parse import urlparse, parse_qs
from .constants import SLUG_STOP_WORDS, LEGACY_SUFFIXES


def normalize_full_url(url: str) -> str:
    """
    Normalize a complete URL for comparison.
    Removes protocol, www, query params, trailing slash, fragments.
    Used for exact URL matching.
    
    Example:
        https://www.example.com/page/?utm=123#section
        → example.com/page
    """
    if not url:
        return ''
    
    try:
        parsed = urlparse(url.lower().strip())
        
        # Remove www prefix
        domain = parsed.netloc.replace('www.', '')
        
        # Remove trailing slash from path
        path = parsed.path.rstrip('/')
        
        # Combine domain + path (no query, no fragment)
        normalized = f"{domain}{path}"
        
        return normalized
    except Exception:
        return url.lower().strip()


def normalize_path(url: str) -> str:
    """
    Extract and normalize just the path portion of a URL.
    Removes query params, trailing slash, but keeps leading slash.
    Used for path-based classification and comparison.
    
    Example:
        https://example.com/blog/post-title/?page=2
        → /blog/post-title
    """
    if not url:
        return '/'
    
    try:
        parsed = urlparse(url.strip())
        path = parsed.path.lower()
        
        # Remove trailing slash but keep leading slash
        if path.endswith('/') and len(path) > 1:
            path = path.rstrip('/')
        
        # Ensure leading slash
        if not path.startswith('/'):
            path = '/' + path
        
        return path
    except Exception:
        return '/'


def get_path_parts(url: str) -> list:
    """
    Extract path parts as a list (without empty strings).
    
    Example:
        /service-area/event-planner/brooklyn/
        → ['service-area', 'event-planner', 'brooklyn']
    """
    path = normalize_path(url)
    return [p for p in path.strip('/').split('/') if p]


def get_folder_root(url: str) -> str:
    """
    Get the top-level folder from a URL path.
    
    Example:
        /product-category/dance/jazz/
        → product-category
    """
    parts = get_path_parts(url)
    return parts[0] if parts else ''


def get_parent_path(url: str) -> str:
    """
    Get the parent path of a URL (everything except the last segment).
    
    Example:
        /shop/clothing/shirts/
        → /shop/clothing
    """
    parts = get_path_parts(url)
    if len(parts) <= 1:
        return '/'
    return '/' + '/'.join(parts[:-1])


def get_slug_last(url: str) -> str:
    """
    Get the last slug segment from a URL.
    
    Example:
        /product-category/dance/jazz/
        → jazz
    """
    parts = get_path_parts(url)
    return parts[-1] if parts else ''


def extract_slug_tokens(url: str, remove_stop_words: bool = True) -> Set[str]:
    """
    Extract meaningful tokens from a URL slug for comparison.
    
    Example:
        /blog/2024/best-dance-shoes-for-beginners/
        → {'best', 'dance', 'shoes', 'beginners'}
    """
    path = normalize_path(url)
    parts = get_path_parts(path)
    
    # Split each part by hyphens and underscores
    tokens = set()
    for part in parts:
        tokens.update(re.split(r'[-_]', part.lower()))
    
    # Filter years (2015-2030)
    tokens = {t for t in tokens if not (t.isdigit() and 2015 <= int(t) <= 2030)}
    
    # Filter short tokens (< 3 chars)
    tokens = {t for t in tokens if len(t) >= 3}
    
    # Remove stop words if requested
    if remove_stop_words:
        tokens = tokens - SLUG_STOP_WORDS
    
    return tokens


def slug_similarity(url1: str, url2: str) -> float:
    """
    Calculate Jaccard similarity between URL slug tokens.
    Returns value between 0.0 and 1.0.
    
    Used for NEAR_DUPLICATE_CONTENT detection.
    """
    tokens1 = extract_slug_tokens(url1, remove_stop_words=True)
    tokens2 = extract_slug_tokens(url2, remove_stop_words=True)
    
    if not tokens1 and not tokens2:
        return 0.0
    
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    
    if not union:
        return 0.0
    
    return len(intersection) / len(union)


def is_legacy_variant(url: str) -> bool:
    """
    Check if a URL contains a legacy suffix pattern.
    
    Examples:
        /page-old/ → True
        /service-backup/ → True
        /product-2/ → True
        /service-area/brooklyn/ → False
    """
    if not url:
        return False
    
    slug_last = get_slug_last(url)
    
    for suffix in LEGACY_SUFFIXES:
        if slug_last.endswith(suffix):
            return True
    
    return False


def strip_legacy_suffix(url: str) -> str:
    """
    Remove legacy suffix from URL to find canonical version.
    
    Example:
        /services/event-planning-old/
        → /services/event-planning/
    """
    if not url:
        return url
    
    parts = get_path_parts(url)
    if not parts:
        return url
    
    last_slug = parts[-1]
    
    for suffix in LEGACY_SUFFIXES:
        if last_slug.endswith(suffix):
            clean_slug = last_slug[:-len(suffix)].rstrip('-')
            parts[-1] = clean_slug
            return '/' + '/'.join(parts)
    
    return url


def normalize_geo(slug: str) -> str:
    """
    Normalize geographic slug for comparison.
    Handles common variations like dashes vs spaces.
    
    Example:
        'new-york' → 'newyork'
        'san francisco' → 'sanfrancisco'
    """
    if not slug:
        return ''
    
    normalized = slug.lower().strip()
    normalized = re.sub(r'[-\s_]', '', normalized)
    
    return normalized


def extract_geo_node(url: str) -> Optional[str]:
    """
    Extract the geographic node (city/location slug) from a location URL.
    
    Example:
        /service-area/event-planner/brooklyn/
        → brooklyn
    """
    parts = get_path_parts(url)
    
    location_folders = {'service-area', 'service-areas', 'locations', 'location', 'city', 'cities'}
    
    # Pattern: <location_folder>/<service?>/<city>
    if len(parts) >= 2 and parts[0] in location_folders:
        # Last part is likely the city
        return parts[-1]
    
    return None


def extract_title_template(title: str, geo_node: str = None) -> str:
    """
    Extract title template by removing geographic node.
    Used for LOCATION_BOILERPLATE detection.
    
    Example:
        title="Event Planner in Brooklyn | CoCo Events"
        geo_node="brooklyn"
        → "Event Planner in | CoCo Events"
    """
    if not title:
        return ''
    
    template = title.lower()
    
    if geo_node:
        # Remove both dashed and spaced versions
        geo_variations = [
            geo_node.lower(),
            geo_node.replace('-', ' ').lower(),
            geo_node.replace('_', ' ').lower(),
        ]
        
        for geo_var in geo_variations:
            template = template.replace(geo_var, '')
    
    # Normalize whitespace
    template = re.sub(r'\s+', ' ', template).strip()
    
    return template


def is_direct_parent(parent_url: str, child_url: str) -> bool:
    """
    Check if parent_url is a direct parent of child_url in the path hierarchy.
    
    Example:
        parent: /services/
        child: /services/event-planning/
        → True
        
        parent: /services/
        child: /services/event-planning/weddings/
        → False (not direct)
    """
    parent_parts = get_path_parts(parent_url)
    child_parts = get_path_parts(child_url)
    
    # Child must have exactly one more part than parent
    if len(child_parts) != len(parent_parts) + 1:
        return False
    
    # All parent parts must match child parts
    return parent_parts == child_parts[:len(parent_parts)]


def has_distinct_subtopic(child_url: str, parent_url: str) -> bool:
    """
    Check if child URL has a distinct subtopic slug (not just a modifier).
    
    Example:
        parent: /services/
        child: /services/corporate-events/
        → True (distinct subtopic)
        
        parent: /services/event-planning/
        child: /services/event-planning-services/
        → False (just a modifier)
    """
    parent_slug = get_slug_last(parent_url)
    child_slug = get_slug_last(child_url)
    
    if not parent_slug or not child_slug:
        return False
    
    # Check if child slug is just parent slug + modifier
    parent_tokens = set(parent_slug.split('-'))
    child_tokens = set(child_slug.split('-'))
    
    # If child contains all parent tokens, it's likely just a variant
    if parent_tokens.issubset(child_tokens):
        return False
    
    return True


def extract_service_keyword(url: str) -> Optional[str]:
    """
    Extract service keyword from a service or location URL.
    
    Example:
        /service-area/event-planner/brooklyn/
        → event-planner
    """
    parts = get_path_parts(url)
    
    location_folders = {'service-area', 'service-areas', 'locations', 'location'}
    service_folders = {'service', 'services', 'residential', 'commercial'}
    
    # Location pattern: <location_folder>/<service>/<city>
    if len(parts) >= 3 and parts[0] in location_folders:
        return parts[1]
    
    # Service pattern: <service_folder>/<service_name>
    if len(parts) >= 2 and parts[0] in service_folders:
        return parts[1]
    
    return None


def is_branded_query(query: str, brand_name: str = None, homepage_title: str = None) -> bool:
    """
    Detect if a query is branded (mentions the business name).
    Branded queries are excluded from cannibalization detection.
    
    Args:
        query: Search query
        brand_name: Known brand name (from onboarding)
        homepage_title: Fallback to extract brand from homepage title
    """
    if not query:
        return False
    
    query_lower = query.lower()
    
    # Check explicit brand name
    if brand_name and brand_name.lower() in query_lower:
        return True
    
    # Try to extract brand from homepage title (first part before separator)
    if homepage_title:
        # Common separators: | - –
        parts = re.split(r'\s+[\|\-–]\s+', homepage_title)
        if parts and len(parts[0]) > 3:
            brand_candidate = parts[0].strip().lower()
            if brand_candidate in query_lower:
                return True
    
    # Check for company indicators
    from .constants import BRANDED_QUERY_INDICATORS
    for indicator in BRANDED_QUERY_INDICATORS:
        if indicator in query_lower:
            return True
    
    return False


def classify_query_intent(query: str) -> Tuple[str, bool]:
    """
    Classify query intent and detect local modifier.
    
    Returns:
        (intent, has_local_modifier)
        intent: 'transactional', 'informational', 'listicle', 'navigational', 'ambiguous'
    """
    from .constants import INTENT_MARKERS, GEO_MODIFIERS
    
    query_lower = query.lower()
    
    # Check for local modifier
    has_local = any(geo in query_lower for geo in GEO_MODIFIERS)
    
    # Check intent markers (order matters - most specific first)
    for intent, markers in INTENT_MARKERS.items():
        for marker in markers:
            if marker in query_lower:
                return intent, has_local
    
    # Default to ambiguous if no clear signals
    return 'ambiguous', has_local


def is_plural_query(query: str) -> bool:
    """
    Detect if query appears to be plural (category intent vs product intent).
    
    Example:
        'dance shoes' → True (category)
        'jazz shoe model X' → False (product)
    """
    if not query:
        return False
    
    words = query.lower().split()
    if not words:
        return False
    
    # Check last significant word
    last_word = words[-1]
    
    # Simple heuristic: ends in 's' but not 'ss' or 'us'
    if last_word.endswith('s') and not last_word.endswith(('ss', 'us', 'is')):
        return True
    
    return False
