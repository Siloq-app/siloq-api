"""
Phase 4: GSC Validation

Uses Google Search Console data to:
1. Confirm static detection issues (upgrade POTENTIAL → CONFIRMED)
2. Detect NEW conflicts not found in Phase 3
3. Calculate severity based on impression distribution

Logic:
- Primary share >= 85% = NOT cannibalization (Google has decided)
- Secondary share >= 15% = CONFIRMED cannibalization
- Severity: SEVERE (3+ pages 10%+), HIGH (secondary 35%+), MEDIUM (secondary 15-35%)
- Upgrades matching SITE_DUPLICATION issues to SEARCH_CONFLICT bucket
- Excludes branded queries
- Filters noise (< 5% share AND 0 clicks)
"""
from typing import List, Dict, Optional
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
    brand_name: str = None,
    homepage_title: str = None
) -> List[Dict]:
    """
    Phase 4: Validate with GSC data.
    
    Args:
        classifications: Page classifications from Phase 1
        gsc_data: List of GSC rows with keys: query, page, clicks, impressions, position
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
    
    # Analyze each query group
    for query, rows in query_groups.items():
        if len(rows) < 2:
            continue
        
        issue = _analyze_query_group(query, rows)
        if issue:
            issues.append(issue)
    
    return issues


def _analyze_query_group(query: str, rows: List[Dict]) -> Optional[Dict]:
    """
    Analyze a single query with multiple competing pages.
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
    
    # Calculate severity
    severity = _calculate_severity(rows)
    
    # Classify query and pages
    query_intent, has_local = classify_query_intent(query)
    is_plural = is_plural_query(query)
    
    # Build issue
    issue = {
        'conflict_type': 'GSC_CONFIRMED',
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


def _calculate_severity(rows: List[Dict]) -> str:
    """
    Calculate severity based on impression distribution.
    
    SEVERE: 3+ pages each with 10%+ share
    HIGH: Secondary page has 35%+ share
    MEDIUM: Secondary page has 15-35% share
    LOW: Minor split
    """
    # Count pages with 10%+ share
    pages_10_plus = sum(1 for r in rows if r['share'] >= 0.10)
    
    if pages_10_plus >= 3:
        return 'SEVERE'
    
    if len(rows) >= 2:
        secondary_share = rows[1]['share']
        if secondary_share >= 0.35:
            return 'HIGH'
        elif secondary_share >= 0.15:
            return 'MEDIUM'
    
    return 'LOW'


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
