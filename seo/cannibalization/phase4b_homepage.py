"""
Phase 4b: Homepage Cannibalization Detection

Detects two distinct homepage anti-patterns using GSC data:

1. HOMEPAGE_CANNIBALIZATION (HIGH severity)
   - Homepage AND a dedicated service/product page BOTH receive impressions for
     the same query.  Traffic is split — the homepage steals authority that
     the service page should own exclusively.

2. HOMEPAGE_CANNIBALIZATION / hoarding sub-type (MEDIUM severity)
   - Homepage is the SOLE ranking page for a non-brand service/product query.
     No dedicated page is receiving any impressions, meaning the homepage is
     "hoarding" the keyword instead of delegating it to the correct page.

ABSOLUTE RULE: Homepage NEVER wins a service/product keyword conflict.
Resolution for both patterns is always DE_OPTIMIZE_HOMEPAGE — never
redirect, merge, or canonicalize the homepage.

This module is intentionally separate from phase4_gsc_validate.py to avoid
touching existing phase logic (per minimal-impact policy).
"""
from collections import defaultdict
from typing import List, Dict, Optional

from .models import PageClassification
from .utils import (
    normalize_full_url,
    is_branded_query,
    classify_query_intent,
    is_plural_query,
)
from .constants import MIN_IMPRESSIONS_THRESHOLD

# Page types that indicate a dedicated, rankable service/product/category page.
# The homepage must never outrank or compete with these for service keywords.
_SERVICE_PRODUCT_TYPES = frozenset({
    'service',
    'service_hub',
    'service_spoke',
    'product',
    'category',
    'category_woo',
    'category_shop',
    'location',
})


def detect_homepage_cannibalization(
    classifications: List[PageClassification],
    gsc_data: List[Dict],
    brand_name: str = '',
) -> List[Dict]:
    """
    Detect homepage cannibalization and hoarding from GSC impression data.

    Args:
        classifications: All page classifications produced by Phase 1.
        gsc_data:        Raw GSC rows — each a dict with keys:
                         'query', 'page', 'clicks', 'impressions', 'position'
        brand_name:      Site brand name used to filter branded queries.

    Returns:
        List of conflict dicts in the same format used by Phase 4.
        Each dict has keys: conflict_type, severity, pages, metadata.
    """
    if not gsc_data or not classifications:
        return []

    # ------------------------------------------------------------------
    # 1. Index PageClassification objects by normalized URL.
    # ------------------------------------------------------------------
    url_to_page: Dict[str, PageClassification] = {}
    for pc in classifications:
        url_to_page[pc.normalized_url] = pc

    # Identify all homepage classifications.
    homepage_urls = {
        pc.normalized_url
        for pc in classifications
        if pc.classified_type == 'homepage'
    }

    if not homepage_urls:
        # No homepage found — nothing to check.
        return []

    # ------------------------------------------------------------------
    # 2. Group GSC data by query → list of {url, page_class, …} rows.
    #    Skip branded queries and rows below the minimum impressions bar.
    # ------------------------------------------------------------------
    query_groups: Dict[str, List[Dict]] = defaultdict(list)

    for row in gsc_data:
        query = row.get('query', '').strip().lower()
        page_url = row.get('page', '').strip()
        clicks = int(row.get('clicks', 0))
        impressions = int(row.get('impressions', 0))
        position = float(row.get('position', 0))

        if not query or not page_url:
            continue
        if impressions < MIN_IMPRESSIONS_THRESHOLD:
            continue
        if is_branded_query(query, brand_name):
            continue

        normalized = normalize_full_url(page_url)
        page_class = url_to_page.get(normalized)
        if not page_class:
            continue

        query_groups[query].append({
            'page_url': page_url,
            'normalized_url': normalized,
            'page_class': page_class,
            'clicks': clicks,
            'impressions': impressions,
            'position': position,
        })

    # ------------------------------------------------------------------
    # 3. Examine each query group for homepage involvement.
    # ------------------------------------------------------------------
    issues: List[Dict] = []

    for query, rows in query_groups.items():
        issue = _analyze_query_for_homepage(query, rows, homepage_urls)
        if issue:
            issues.append(issue)

    return issues


def _analyze_query_for_homepage(
    query: str,
    rows: List[Dict],
    homepage_urls: frozenset,
) -> Optional[Dict]:
    """
    Check a single query group for homepage cannibalization patterns.

    Returns a conflict dict or None if no homepage issue is detected.
    """
    # Partition rows into homepage rows and service/product page rows.
    homepage_rows = [r for r in rows if r['normalized_url'] in homepage_urls]
    service_rows = [
        r for r in rows
        if r['page_class'].classified_type in _SERVICE_PRODUCT_TYPES
    ]

    if not homepage_rows:
        # Homepage not ranking for this query — nothing to flag.
        return None

    # Sort by impressions descending for consistent ordering.
    homepage_rows.sort(key=lambda r: r['impressions'], reverse=True)
    service_rows.sort(key=lambda r: r['impressions'], reverse=True)

    homepage_row = homepage_rows[0]
    total_homepage_imps = homepage_row['impressions']

    query_intent, has_local = classify_query_intent(query)
    plural = is_plural_query(query)

    if service_rows:
        # ------------------------------------------------------------------
        # Pattern A: Homepage AND a service/product page both have impressions.
        # This is active traffic splitting — HIGH severity.
        # ------------------------------------------------------------------
        all_rows = homepage_rows + service_rows
        total_imps = sum(r['impressions'] for r in all_rows)
        total_clicks = sum(r['clicks'] for r in all_rows)

        # Build share data for severity calculation.
        share_rows = [
            {'share': r['impressions'] / total_imps} for r in all_rows
        ]
        severity = _calculate_severity(share_rows)

        pages = [homepage_row['page_class']] + [r['page_class'] for r in service_rows]
        gsc_rows = _build_gsc_rows(all_rows, total_imps)

        return {
            'conflict_type': 'HOMEPAGE_CANNIBALIZATION',
            'severity': severity,
            'pages': pages,
            'gsc_validated': True,
            'metadata': {
                'query': query,
                'query_intent': query_intent,
                'has_local_modifier': has_local,
                'is_plural_query': plural,
                'total_impressions': total_imps,
                'total_clicks': total_clicks,
                'page_count': len(pages),
                'homepage_pattern': 'cannibalization',
                'homepage_url': homepage_row['page_url'],
                'gsc_rows': gsc_rows,
            },
        }

    # ------------------------------------------------------------------
    # Pattern B: Homepage is the ONLY ranking page for a service query.
    # No dedicated service page is capturing impressions — MEDIUM severity.
    # Only flag this when query intent is transactional (service/product
    # queries); informational / navigational queries on the homepage are
    # acceptable.
    # ------------------------------------------------------------------
    if query_intent not in ('transactional', 'commercial'):
        return None

    return {
        'conflict_type': 'HOMEPAGE_CANNIBALIZATION',
        'severity': 'MEDIUM',
        'pages': [homepage_row['page_class']],
        'gsc_validated': True,
        'metadata': {
            'query': query,
            'query_intent': query_intent,
            'has_local_modifier': has_local,
            'is_plural_query': plural,
            'total_impressions': total_homepage_imps,
            'total_clicks': homepage_row['clicks'],
            'page_count': 1,
            'homepage_pattern': 'hoarding',
            'homepage_url': homepage_row['page_url'],
            'gsc_rows': _build_gsc_rows(homepage_rows, total_homepage_imps),
        },
    }


def _build_gsc_rows(rows: List[Dict], total_imps: int) -> List[Dict]:
    """Format GSC rows for conflict metadata."""
    if total_imps == 0:
        total_imps = 1  # Guard against division-by-zero.
    return [
        {
            'url': r['page_url'],
            'normalized_url': r['normalized_url'],
            'page_type': r['page_class'].classified_type,
            'clicks': r['clicks'],
            'impressions': r['impressions'],
            'position': round(r['position'], 1),
            'share': round(r['impressions'] / total_imps * 100, 1),
        }
        for r in rows
    ]


def _calculate_severity(share_rows: List[Dict]) -> str:
    """
    Determine severity from impression share distribution.

    Mirrors the logic in phase4_gsc_validate._calculate_severity so that
    HOMEPAGE_CANNIBALIZATION conflicts are scored consistently.

    SEVERE : 3+ pages each with >= 10% share
    HIGH   : Secondary page has >= 35% share
    MEDIUM : Secondary page has 15–35% share
    LOW    : Minor split
    """
    pages_10_plus = sum(1 for r in share_rows if r['share'] >= 0.10)
    if pages_10_plus >= 3:
        return 'SEVERE'
    if len(share_rows) >= 2:
        secondary_share = share_rows[1]['share']
        if secondary_share >= 0.35:
            return 'HIGH'
        if secondary_share >= 0.15:
            return 'MEDIUM'
    return 'LOW'
