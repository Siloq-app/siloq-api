"""
Phase 5: Wrong Winner Detection

Identifies cases where the WRONG page is ranking for a query.
This is NOT cannibalization (no competition) - it's a strategy issue.

Mismatch types:
- INTENT_MISMATCH: Blog ranking for transactional query
- GEOGRAPHIC_MISMATCH: Wrong city's location page ranking
- PAGE_TYPE_MISMATCH: Product ranking for plural (category) query
- HOMEPAGE_HOARDING: Homepage ranking for specific service query

Badge: WRONG_WINNER (blue)
Bucket: WRONG_WINNER
"""
from typing import List, Dict, Optional
from collections import defaultdict
from .models import PageClassification
from .utils import classify_query_intent, is_plural_query, normalize_geo
from .constants import CONFLICT_TYPES


def run_phase5(
    classifications: List[PageClassification],
    gsc_data: List[Dict],
    brand_name: str = None,
    homepage_title: str = None
) -> List[Dict]:
    """
    Phase 5: Detect wrong winner cases.
    
    Runs on ALL queries (not just conflicts).
    """
    if not gsc_data:
        return []
    
    issues = []
    
    # Build lookup
    url_to_page = {pc.normalized_url: pc for pc in classifications}
    
    # Group GSC data by query
    from .utils import normalize_full_url, is_branded_query
    from .constants import MIN_IMPRESSIONS_THRESHOLD
    
    query_groups = defaultdict(list)
    for row in gsc_data:
        query = row.get('query', '').strip().lower()
        page_url = row.get('page', '').strip()
        clicks = int(row.get('clicks', 0))
        impressions = int(row.get('impressions', 0))
        position = float(row.get('position', 0))
        
        if impressions < MIN_IMPRESSIONS_THRESHOLD:
            continue
        
        # Skip branded queries
        if is_branded_query(query, brand_name, homepage_title):
            continue
        
        normalized = normalize_full_url(page_url)
        page_class = url_to_page.get(normalized)
        if not page_class:
            continue
        
        query_groups[query].append({
            'query': query,
            'page_url': page_url,
            'normalized_url': normalized,
            'page_class': page_class,
            'clicks': clicks,
            'impressions': impressions,
            'position': position,
        })
    
    # Analyze each query
    for query, rows in query_groups.items():
        # Sort by impressions (winner = most impressions)
        rows = sorted(rows, key=lambda r: r['impressions'], reverse=True)
        winner = rows[0]
        
        issue = _detect_wrong_winner(query, winner, rows, classifications)
        if issue:
            issues.append(issue)
    
    return issues


def _detect_wrong_winner(
    query: str,
    winner: Dict,
    all_rows: List[Dict],
    classifications: List[PageClassification]
) -> Optional[Dict]:
    """
    Check if the winning page is the wrong page type for this query.
    """
    winner_page = winner['page_class']
    query_intent, has_local = classify_query_intent(query)
    is_plural = is_plural_query(query)
    
    # MISMATCH 1: INTENT_MISMATCH
    # Blog/listicle ranking for transactional query
    if query_intent == 'transactional' and winner_page.classified_type in ['blog']:
        # Check if a better page exists (category or service)
        better_pages = [
            pc for pc in classifications
            if pc.classified_type in ['category_woo', 'category_shop', 'category_custom', 'service_hub', 'service_spoke', 'product']
            and _has_query_overlap(query, pc)
        ]
        
        if better_pages:
            return {
                'conflict_type': 'INTENT_MISMATCH',
                'severity': 'MEDIUM',
                'pages': [winner_page] + better_pages[:2],  # Winner + up to 2 better options
                'metadata': {
                    'query': query,
                    'query_intent': query_intent,
                    'winner_type': winner_page.classified_type,
                    'expected_type': 'category or service',
                    'impressions': winner['impressions'],
                    'clicks': winner['clicks'],
                },
            }
    
    # MISMATCH 2: PAGE_TYPE_MISMATCH
    # Product ranking for plural (category) query
    if is_plural and winner_page.classified_type == 'product':
        # Check if a category page exists
        category_pages = [
            pc for pc in classifications
            if pc.classified_type in ['category_woo', 'category_shop', 'category_custom']
            and _has_query_overlap(query, pc)
        ]
        
        if category_pages:
            return {
                'conflict_type': 'PAGE_TYPE_MISMATCH',
                'severity': 'MEDIUM',
                'pages': [winner_page] + category_pages[:1],
                'metadata': {
                    'query': query,
                    'winner_type': 'product',
                    'expected_type': 'category',
                    'impressions': winner['impressions'],
                    'clicks': winner['clicks'],
                },
            }
    
    # MISMATCH 3: HOMEPAGE_HOARDING
    # Homepage ranking for specific service/product query
    if winner_page.classified_type == 'homepage':
        # Check if a specific page exists
        specific_pages = [
            pc for pc in classifications
            if pc.classified_type in ['service_hub', 'service_spoke', 'product', 'category_woo', 'category_shop']
            and _has_query_overlap(query, pc)
        ]
        
        if specific_pages:
            return {
                'conflict_type': 'HOMEPAGE_HOARDING',
                'severity': 'MEDIUM',
                'pages': [winner_page] + specific_pages[:2],
                'metadata': {
                    'query': query,
                    'winner_type': 'homepage',
                    'expected_type': specific_pages[0].classified_type,
                    'impressions': winner['impressions'],
                    'clicks': winner['clicks'],
                },
            }
    
    # MISMATCH 4: GEOGRAPHIC_MISMATCH
    # Wrong location page ranking (if query contains city name)
    if has_local and winner_page.classified_type == 'location':
        # Try to extract city from query
        query_city = _extract_city_from_query(query)
        
        if query_city:
            # Normalize
            query_city_norm = normalize_geo(query_city)
            winner_city_norm = normalize_geo(winner_page.geo_node) if winner_page.geo_node else ''
            
            # Check if they match
            if query_city_norm and winner_city_norm and query_city_norm != winner_city_norm:
                # Find the correct location page
                correct_pages = [
                    pc for pc in classifications
                    if pc.classified_type == 'location'
                    and normalize_geo(pc.geo_node) == query_city_norm
                ]
                
                if correct_pages:
                    return {
                        'conflict_type': 'GEOGRAPHIC_MISMATCH',
                        'severity': 'HIGH',
                        'pages': [winner_page, correct_pages[0]],
                        'metadata': {
                            'query': query,
                            'query_city': query_city,
                            'winner_city': winner_page.geo_node,
                            'correct_city': correct_pages[0].geo_node,
                            'impressions': winner['impressions'],
                            'clicks': winner['clicks'],
                        },
                    }
    
    return None


def _has_query_overlap(query: str, page: PageClassification) -> bool:
    """
    Check if query keywords overlap with page slug tokens.
    Simple heuristic: at least one significant query word appears in page slug.
    """
    from .constants import SLUG_STOP_WORDS
    
    query_words = set(query.lower().split())
    query_words = query_words - SLUG_STOP_WORDS
    
    page_tokens = set(page.slug_tokens_json) if page.slug_tokens_json else set()
    
    overlap = query_words & page_tokens
    return len(overlap) > 0


def _extract_city_from_query(query: str) -> Optional[str]:
    """
    Try to extract city name from query.
    Simple heuristic: look for common patterns.
    
    Example:
        "event planner in brooklyn" → "brooklyn"
        "brooklyn event planning" → "brooklyn"
    """
    query_lower = query.lower()
    
    # Pattern: "in <city>"
    import re
    match = re.search(r'\bin\s+([a-z]+(?:\s+[a-z]+)?)', query_lower)
    if match:
        return match.group(1).strip()
    
    # Pattern: "near <city>"
    match = re.search(r'\bnear\s+([a-z]+(?:\s+[a-z]+)?)', query_lower)
    if match:
        return match.group(1).strip()
    
    # Pattern: "<city> <service>"
    # This is harder without a city database, so we skip for now
    
    return None
