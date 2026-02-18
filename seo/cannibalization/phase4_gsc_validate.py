"""
Phase 4: GSC Validation

Uses Google Search Console data to:
1. Confirm static detection issues (upgrade POTENTIAL → CONFIRMED)
2. Detect NEW conflicts not found in Phase 3
3. Calculate severity based on impression distribution
4. **NEW: Detect flip-flop behavior between competing pages**

Logic:
- Primary share >= 85% = NOT cannibalization (Google has decided)
- Secondary share >= 15% = CONFIRMED cannibalization
- Severity: SEVERE (3+ pages 10%+), HIGH (secondary 35%+), MEDIUM (secondary 15-35%)
- Upgrades matching SITE_DUPLICATION issues to SEARCH_CONFLICT bucket
- Excludes branded queries
- Filters noise (< 5% share AND 0 clicks)
- **Flip-Flop Detection**: Negative correlation between daily positions signals alternating rankings
"""
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
from .models import PageClassification
from .utils import is_branded_query, classify_query_intent, is_plural_query
from .constants import (
    MIN_IMPRESSIONS_THRESHOLD,
    PRIMARY_SHARE_THRESHOLD,
    SECONDARY_SHARE_THRESHOLD,
    NOISE_FILTER_SHARE,
    SEVERITY_THRESHOLDS,
)


def run_phase4(
    classifications: List[PageClassification],
    gsc_data: List[Dict],
    gsc_daily_data: List[Dict] = None,
    brand_name: str = None,
    homepage_title: str = None
) -> List[Dict]:
    """
    Phase 4: Validate with GSC data.
    
    Args:
        classifications: Page classifications from Phase 1
        gsc_data: List of GSC rows with keys: query, page, clicks, impressions, position
        gsc_daily_data: List of GSC rows with date dimension for flip-flop detection
        brand_name: Site brand name (from onboarding)
        homepage_title: Fallback for brand detection
    
    Returns:
        List of GSC-validated issue dicts
    """
    if not gsc_data:
        return []
    
    issues = []
    
    # Build lookup: normalized_url → PageClassification
    url_to_page = {}
    for pc in classifications:
        url_to_page[pc.normalized_url] = pc
    
    # Group GSC data by query
    query_groups = defaultdict(list)
    for row in gsc_data:
        query = row.get('query', '').strip().lower()
        page_url = row.get('page', '').strip()
        clicks = int(row.get('clicks', 0))
        impressions = int(row.get('impressions', 0))
        position = float(row.get('position', 0))
        
        # Filter minimum threshold
        if impressions < MIN_IMPRESSIONS_THRESHOLD:
            continue
        
        # Skip branded queries
        if is_branded_query(query, brand_name, homepage_title):
            continue
        
        # Normalize page URL for lookup
        from .utils import normalize_full_url
        normalized = normalize_full_url(page_url)
        
        # Find matching classification
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
    
    # Build daily position data lookup if available
    daily_lookup = _build_daily_position_lookup(gsc_daily_data) if gsc_daily_data else {}
    
    # Analyze each query group
    for query, rows in query_groups.items():
        if len(rows) < 2:
            continue
        
        issue = _analyze_query_group(query, rows, daily_lookup)
        if issue:
            issues.append(issue)
    
    return issues


def _build_daily_position_lookup(gsc_daily_data: List[Dict]) -> Dict:
    """
    Build a lookup: (query, normalized_url) → [(date, position), ...]
    
    Args:
        gsc_daily_data: GSC data with dimensions ['date', 'query', 'page']
    
    Returns:
        Dict mapping (query, url) to list of (date, position) tuples
    """
    from .utils import normalize_full_url
    
    lookup = defaultdict(list)
    for row in gsc_daily_data:
        query = row.get('query', '').strip().lower()
        page_url = row.get('page', '').strip()
        date = row.get('date', '')
        position = float(row.get('position', 0))
        
        if not query or not page_url or not date or position == 0:
            continue
        
        normalized = normalize_full_url(page_url)
        lookup[(query, normalized)].append((date, position))
    
    # Sort by date
    for key in lookup:
        lookup[key] = sorted(lookup[key], key=lambda x: x[0])
    
    return lookup


def _calculate_flip_flop_score(daily_positions_a: List[Tuple[str, float]], 
                                 daily_positions_b: List[Tuple[str, float]]) -> float:
    """
    Calculate Pearson correlation between two pages' daily positions.
    
    Args:
        daily_positions_a/b: list of (date, position) tuples over 28 days
    
    Returns:
        correlation: float (-1 to 1)
        - Negative = flip-flop (when one goes up, other goes down)
        - Near 0 = independent ranking
        - Positive = move together
    """
    if len(daily_positions_a) < 7 or len(daily_positions_b) < 7:
        return 0.0  # Not enough data
    
    # Align by date
    dates_a = {d: p for d, p in daily_positions_a}
    dates_b = {d: p for d, p in daily_positions_b}
    common_dates = sorted(set(dates_a.keys()) & set(dates_b.keys()))
    
    if len(common_dates) < 7:
        return 0.0
    
    positions_a = [dates_a[d] for d in common_dates]
    positions_b = [dates_b[d] for d in common_dates]
    
    # Pure Python Pearson correlation (no numpy)
    return _pearson_correlation(positions_a, positions_b)


def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """
    Calculate Pearson correlation coefficient.
    Pure Python implementation (no numpy required).
    """
    n = len(x)
    if n == 0:
        return 0.0
    
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    std_x = (sum((xi - mean_x)**2 for xi in x) / n) ** 0.5
    std_y = (sum((yi - mean_y)**2 for yi in y) / n) ** 0.5
    
    if std_x == 0 or std_y == 0:
        return 0.0
    
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
    return cov / (std_x * std_y)


def _calculate_position_volatility(daily_positions: List[Tuple[str, float]]) -> float:
    """Calculate standard deviation of daily positions."""
    if len(daily_positions) < 2:
        return 0.0
    
    positions = [p for _, p in daily_positions]
    n = len(positions)
    mean = sum(positions) / n
    variance = sum((p - mean) ** 2 for p in positions) / n
    return variance ** 0.5


def _analyze_query_group(query: str, rows: List[Dict], daily_lookup: Dict) -> Optional[Dict]:
    """
    Analyze a single query with multiple competing pages.
    Now includes flip-flop detection.
    """
    # Sort by impressions descending
    rows = sorted(rows, key=lambda r: r['impressions'], reverse=True)
    
    # Calculate total impressions
    total_imps = sum(r['impressions'] for r in rows)
    if total_imps == 0:
        return None
    
    # Calculate impression shares
    for row in rows:
        row['share'] = row['impressions'] / total_imps
    
    # Filter noise (< 5% share AND 0 clicks)
    rows = [r for r in rows if not (r['share'] < NOISE_FILTER_SHARE and r['clicks'] == 0)]
    
    if len(rows) < 2:
        return None
    
    # Check primary share threshold
    primary = rows[0]
    if primary['share'] >= PRIMARY_SHARE_THRESHOLD:
        # Google has decided - not cannibalization (but pass to Phase 5 for wrong winner check)
        return None
    
    # Check secondary share threshold
    secondary = rows[1]
    if secondary['share'] < SECONDARY_SHARE_THRESHOLD:
        return None
    
    # **NEW: Flip-Flop Detection**
    flip_flop_data = None
    correlation = 0.0
    
    if daily_lookup and len(rows) >= 2:
        primary_url = primary['normalized_url']
        secondary_url = secondary['normalized_url']
        
        daily_a = daily_lookup.get((query, primary_url), [])
        daily_b = daily_lookup.get((query, secondary_url), [])
        
        if daily_a and daily_b:
            correlation = _calculate_flip_flop_score(daily_a, daily_b)
            
            # Calculate position volatility for each page
            volatility_a = _calculate_position_volatility(daily_a)
            volatility_b = _calculate_position_volatility(daily_b)
            
            flip_flop_data = {
                'detected': correlation < -0.5,
                'correlation': round(correlation, 3),
                'primary_volatility': round(volatility_a, 2),
                'secondary_volatility': round(volatility_b, 2),
                'daily_positions': {
                    primary['page_url']: [
                        {'date': d, 'position': round(p, 1)} for d, p in daily_a
                    ],
                    secondary['page_url']: [
                        {'date': d, 'position': round(p, 1)} for d, p in daily_b
                    ],
                }
            }
    
    # Calculate severity (with flip-flop override)
    severity = _calculate_severity(rows, correlation)
    
    # Classify query and pages
    query_intent, has_local = classify_query_intent(query)
    is_plural = is_plural_query(query)
    
    # Sub-type: homepage involvement
    page_types = [r['page_class'].classified_type for r in rows]
    if 'homepage' in page_types:
        # Homepage is splitting impressions with service/product pages
        conflict_type = 'GSC_HOMEPAGE_SPLIT' if primary['page_class'].classified_type != 'homepage' else 'GSC_HOMEPAGE_HOARDING'
    elif 'blog' in page_types and any(t in page_types for t in ['category_woo', 'category_shop', 'service_hub', 'service_spoke']):
        conflict_type = 'GSC_BLOG_VS_CATEGORY'
    else:
        conflict_type = 'GSC_CONFIRMED'
    
    # Override conflict type if flip-flop detected
    if flip_flop_data and flip_flop_data['detected']:
        conflict_type = 'GSC_FLIP_FLOP'
    
    # Build issue
    issue = {
        'conflict_type': conflict_type,
        'severity': severity,
        'pages': [r['page_class'] for r in rows],
        'metadata': {
            'query': query,
            'query_intent': query_intent,
            'has_local_modifier': has_local,
            'is_plural_query': is_plural,
            'total_impressions': total_imps,
            'total_clicks': sum(r['clicks'] for r in rows),
            'page_count': len(rows),
            'flip_flop': flip_flop_data,  # NEW: Flip-flop detection data
            'gsc_rows': [
                {
                    'url': r['page_url'],
                    'normalized_url': r['normalized_url'],
                    'page_type': r['page_class'].classified_type,
                    'clicks': r['clicks'],
                    'impressions': r['impressions'],
                    'position': round(r['position'], 1),
                    'share': round(r['share'] * 100, 1),
                }
                for r in rows
            ],
        },
    }
    
    return issue


def _calculate_severity(rows: List[Dict], correlation: float = 0.0) -> str:
    """
    Calculate severity based on impression distribution and flip-flop correlation.
    
    FLIP-FLOP OVERRIDE: If correlation < -0.5, minimum severity is HIGH
    SEVERE: 3+ pages each with 10%+ share
    HIGH: Secondary page has 35%+ share OR flip-flop detected
    MEDIUM: Secondary page has 15-35% share
    LOW: Minor split
    
    Args:
        rows: List of page data with 'share' key
        correlation: Pearson correlation from flip-flop detection
    """
    # Count pages with 10%+ share
    pages_10_plus = sum(1 for r in rows if r['share'] >= 0.10)
    
    if pages_10_plus >= 3:
        severity = 'SEVERE'
    elif len(rows) >= 2:
        secondary_share = rows[1]['share']
        if secondary_share >= 0.35:
            severity = 'HIGH'
        elif secondary_share >= 0.15:
            severity = 'MEDIUM'
        else:
            severity = 'LOW'
    else:
        severity = 'LOW'
    
    # **Flip-Flop Override**: Strong negative correlation = minimum HIGH severity
    if correlation < -0.5:
        severity_rank = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'SEVERE': 4}
        current_rank = severity_rank.get(severity, 1)
        if current_rank < 3:  # Less than HIGH
            severity = 'HIGH'
    
    # Lower severity if pages rank independently (correlation near 0)
    if -0.3 < correlation < 0.3 and correlation != 0.0:
        severity_rank = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'SEVERE': 4}
        current_rank = severity_rank.get(severity, 1)
        if current_rank > 1:  # Can be lowered
            rank_order = ['LOW', 'MEDIUM', 'HIGH', 'SEVERE']
            severity = rank_order[current_rank - 2]  # Lower by one tier
    
    return severity


def upgrade_static_issues(
    static_issues: List[Dict],
    gsc_issues: List[Dict]
) -> List[Dict]:
    """
    Upgrade matching SITE_DUPLICATION issues to SEARCH_CONFLICT.
    
    If a static issue has page URLs that appear in a GSC issue,
    upgrade it to CONFIRMED and change bucket to SEARCH_CONFLICT.
    """
    upgraded_issues = []
    
    # Build GSC page URL set
    gsc_urls = set()
    for gsc_issue in gsc_issues:
        for row in gsc_issue['metadata'].get('gsc_rows', []):
            gsc_urls.add(row['normalized_url'])
    
    # Check each static issue
    for issue in static_issues:
        pages = issue.get('pages', [])
        page_urls = {pc.normalized_url for pc in pages}
        
        # Check for overlap with GSC data
        overlap = page_urls & gsc_urls
        
        if overlap:
            # Upgrade to CONFIRMED
            issue['badge'] = 'CONFIRMED'
            issue['bucket'] = 'SEARCH_CONFLICT'
            # Keep original conflict_type but add GSC validation flag
            issue['gsc_validated'] = True
        
        upgraded_issues.append(issue)
    
    return upgraded_issues
