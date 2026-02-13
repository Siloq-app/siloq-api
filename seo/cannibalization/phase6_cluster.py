"""
Phase 6: Clustering and Priority Scoring

Groups issues by cluster_key (conflict type + action code must match).
Applies hard cap of 15 pages per cluster.
Calculates priority score: bucket(50) + severity(30) + impressions(20).

SEARCH_CONFLICT always sorts above SITE_DUPLICATION.
"""
from typing import List, Dict
from collections import defaultdict
from .constants import (
    CONFLICT_TYPES,
    BUCKET_SCORES,
    SEVERITY_SCORES,
    MAX_CLUSTER_SIZE,
    IMPRESSION_THRESHOLD_HIGH,
    IMPRESSION_THRESHOLD_MEDIUM,
)


def run_phase6(all_issues: List[Dict]) -> List[Dict]:
    """
    Phase 6: Cluster and prioritize issues.
    
    Args:
        all_issues: Combined list from Phases 3, 4, 5
    
    Returns:
        List of clustered issues with priority scores
    """
    if not all_issues:
        return []
    
    # Group by cluster_key
    cluster_map = defaultdict(lambda: {
        'issues': [],
        'pages': {},  # page_id → PageClassification
        'conflict_type': None,
        'bucket': None,
        'badge': None,
        'severity': None,
        'action_code': None,
        'gsc_data': {},
    })
    
    for issue in all_issues:
        cluster_key = _generate_cluster_key(issue)
        
        cluster = cluster_map[cluster_key]
        cluster['issues'].append(issue)
        
        # Set cluster attributes from first issue (or upgrade)
        if cluster['conflict_type'] is None:
            cluster['conflict_type'] = issue['conflict_type']
            cluster['bucket'] = _get_bucket(issue)
            cluster['badge'] = _get_badge(issue)
            cluster['action_code'] = _get_action_code(issue)
        
        # Upgrade severity if higher
        issue_severity = issue.get('severity', 'LOW')
        if cluster['severity'] is None or _severity_rank(issue_severity) > _severity_rank(cluster['severity']):
            cluster['severity'] = issue_severity
        
        # Collect pages
        for page in issue.get('pages', []):
            if hasattr(page, 'page_id'):
                cluster['pages'][page.page_id] = page
        
        # Merge GSC data
        if 'metadata' in issue:
            meta = issue['metadata']
            if 'total_impressions' in meta:
                cluster['gsc_data']['total_impressions'] = cluster['gsc_data'].get('total_impressions', 0) + meta['total_impressions']
            if 'total_clicks' in meta:
                cluster['gsc_data']['total_clicks'] = cluster['gsc_data'].get('total_clicks', 0) + meta['total_clicks']
            if 'gsc_rows' in meta:
                if 'gsc_rows' not in cluster['gsc_data']:
                    cluster['gsc_data']['gsc_rows'] = []
                cluster['gsc_data']['gsc_rows'].extend(meta['gsc_rows'])
            if 'query' in meta:
                if 'queries' not in cluster['gsc_data']:
                    cluster['gsc_data']['queries'] = []
                cluster['gsc_data']['queries'].append(meta['query'])
    
    # Convert clusters to output format
    clustered_issues = []
    
    for cluster_key, cluster in cluster_map.items():
        # Get all pages
        all_pages = list(cluster['pages'].values())
        
        # Apply size cap (15 pages max)
        if len(all_pages) > MAX_CLUSTER_SIZE:
            all_pages = _split_large_cluster(all_pages, cluster_key)
        
        # Calculate priority score
        priority_score = _calculate_priority(
            cluster['bucket'],
            cluster['severity'],
            cluster['gsc_data'].get('total_impressions', 0)
        )
        
        # Build cluster result
        result = {
            'cluster_key': cluster_key,
            'conflict_type': cluster['conflict_type'],
            'bucket': cluster['bucket'],
            'badge': cluster['badge'],
            'severity': cluster['severity'],
            'action_code': cluster['action_code'],
            'priority_score': priority_score,
            'page_count': len(all_pages),
            'pages': all_pages,
            'gsc_data': cluster['gsc_data'] if cluster['gsc_data'] else None,
            'recommendation': _generate_recommendation(cluster),
        }
        
        clustered_issues.append(result)
    
    # Sort by priority (SEARCH_CONFLICT first, then by score)
    clustered_issues.sort(key=lambda x: (
        0 if x['bucket'] == 'SEARCH_CONFLICT' else 1 if x['bucket'] == 'SITE_DUPLICATION' else 2,
        -x['priority_score']
    ))
    
    return clustered_issues


def _generate_cluster_key(issue: Dict) -> str:
    """
    Generate cluster key for grouping.
    Cluster key must match: conflict_type + action_code + keyword/context.
    """
    conflict_type = issue['conflict_type']
    
    # Get identifying metadata
    metadata = issue.get('metadata', {})
    
    # For legacy cleanup: cluster by base slug
    if conflict_type in ['LEGACY_CLEANUP', 'LEGACY_ORPHAN']:
        legacy_url = metadata.get('legacy_url', '')
        from .utils import strip_legacy_suffix, get_slug_last
        base_slug = get_slug_last(strip_legacy_suffix(legacy_url))
        return f"{conflict_type}:{base_slug}"
    
    # For taxonomy clash: cluster by shared slug
    if conflict_type == 'TAXONOMY_CLASH':
        shared_slug = metadata.get('shared_slug', 'unknown')
        return f"{conflict_type}:{shared_slug}"
    
    # For location boilerplate: cluster by title template
    if conflict_type == 'LOCATION_BOILERPLATE':
        template = metadata.get('title_template', 'unknown')[:50]
        return f"{conflict_type}:{template}"
    
    # For context duplicate: cluster by service keyword
    if conflict_type == 'CONTEXT_DUPLICATE':
        service_kw = metadata.get('service_keyword', 'unknown')
        return f"{conflict_type}:{service_kw}"
    
    # For GSC confirmed: cluster by query
    if conflict_type == 'GSC_CONFIRMED':
        query = metadata.get('query', 'unknown')
        return f"{conflict_type}:{query}"
    
    # For wrong winner types: cluster by query
    if conflict_type in ['INTENT_MISMATCH', 'GEOGRAPHIC_MISMATCH', 'PAGE_TYPE_MISMATCH', 'HOMEPAGE_HOARDING']:
        query = metadata.get('query', 'unknown')
        return f"{conflict_type}:{query}"
    
    # For near duplicates: use similarity hash (page IDs sorted)
    if conflict_type == 'NEAR_DUPLICATE_CONTENT':
        pages = issue.get('pages', [])
        page_ids = sorted([p.page_id for p in pages if hasattr(p, 'page_id')])
        return f"{conflict_type}:{'_'.join(map(str, page_ids))}"
    
    # Default
    return f"{conflict_type}:default"


def _get_bucket(issue: Dict) -> str:
    """Get bucket for issue."""
    conflict_type = issue['conflict_type']
    
    # Check if GSC validated
    if issue.get('gsc_validated') or conflict_type.startswith('GSC_'):
        return 'SEARCH_CONFLICT'
    
    # Wrong winner types
    if conflict_type in ['INTENT_MISMATCH', 'GEOGRAPHIC_MISMATCH', 'PAGE_TYPE_MISMATCH', 'HOMEPAGE_HOARDING']:
        return 'WRONG_WINNER'
    
    # Default to site duplication
    return 'SITE_DUPLICATION'


def _get_badge(issue: Dict) -> str:
    """Get badge for issue."""
    bucket = _get_bucket(issue)
    
    if bucket == 'SEARCH_CONFLICT':
        return 'CONFIRMED'
    elif bucket == 'WRONG_WINNER':
        return 'WRONG_WINNER'
    else:
        return 'POTENTIAL'


def _get_action_code(issue: Dict) -> str:
    """Get action code for issue."""
    conflict_type = issue['conflict_type']
    
    action_map = {
        'TAXONOMY_CLASH': 'REDIRECT_TO_CANONICAL',
        'LEGACY_CLEANUP': 'REDIRECT_TO_CANONICAL',
        'LEGACY_ORPHAN': 'REVIEW_AND_REDIRECT',
        'NEAR_DUPLICATE_CONTENT': 'REDIRECT_TO_CANONICAL',
        'CONTEXT_DUPLICATE': 'REDIRECT_OR_DIFFERENTIATE',
        'LOCATION_BOILERPLATE': 'REWRITE_LOCAL_EVIDENCE',
        'GSC_CONFIRMED': 'REDIRECT_TO_CANONICAL',
        'INTENT_MISMATCH': 'STRENGTHEN_CORRECT_PAGE',
        'GEOGRAPHIC_MISMATCH': 'REWRITE_LOCAL_EVIDENCE',
        'PAGE_TYPE_MISMATCH': 'STRENGTHEN_CORRECT_PAGE',
        'HOMEPAGE_HOARDING': 'STRENGTHEN_CORRECT_PAGE',
    }
    
    return action_map.get(conflict_type, 'REVIEW_AND_REDIRECT')


def _severity_rank(severity: str) -> int:
    """Convert severity to rank (higher = worse)."""
    ranks = {'SEVERE': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
    return ranks.get(severity, 0)


def _calculate_priority(bucket: str, severity: str, impressions: int) -> int:
    """
    Calculate priority score.
    
    Formula: bucket(50) + severity(30) + impressions(20)
    """
    bucket_score = BUCKET_SCORES.get(bucket, 0)
    severity_score = SEVERITY_SCORES.get(severity, 0)
    
    # Impression score (0-20 points)
    if impressions >= IMPRESSION_THRESHOLD_HIGH:
        impression_score = 20
    elif impressions >= IMPRESSION_THRESHOLD_MEDIUM:
        impression_score = 10
    elif impressions > 0:
        impression_score = 5
    else:
        impression_score = 0
    
    return bucket_score + severity_score + impression_score


def _split_large_cluster(pages: list, cluster_key: str) -> list:
    """
    Split large clusters (>15 pages) by folder_root, then chunk.
    Returns only the first chunk (top 15 by priority).
    """
    # Group by folder_root
    from collections import defaultdict
    folder_groups = defaultdict(list)
    for page in pages:
        folder_groups[page.folder_root].append(page)
    
    # If splitting by folder results in smaller groups, return largest group
    if len(folder_groups) > 1:
        largest_group = max(folder_groups.values(), key=len)
        if len(largest_group) <= MAX_CLUSTER_SIZE:
            return largest_group[:MAX_CLUSTER_SIZE]
    
    # Otherwise, just return first 15
    return pages[:MAX_CLUSTER_SIZE]


def _generate_recommendation(cluster: Dict) -> str:
    """Generate human-readable recommendation."""
    conflict_type = cluster['conflict_type']
    action_code = cluster['action_code']
    page_count = len(cluster['pages'])
    
    recommendations = {
        'TAXONOMY_CLASH': f"Choose ONE canonical folder structure for these {page_count} pages. Redirect duplicates via 301.",
        'LEGACY_CLEANUP': f"Redirect {page_count} legacy pages to their clean versions via 301.",
        'LEGACY_ORPHAN': f"Review {page_count} orphaned legacy pages. Either redirect to a current page or update the URL.",
        'NEAR_DUPLICATE_CONTENT': f"Consolidate {page_count} near-duplicate pages. Choose canonical, redirect others.",
        'CONTEXT_DUPLICATE': f"Either merge {page_count} duplicate service pages or differentiate with unique content (70%+ different).",
        'LOCATION_BOILERPLATE': f"Rewrite {page_count} location pages with unique local evidence: venue names, local reviews, neighborhood photos.",
        'GSC_CONFIRMED': f"Google sees {page_count} pages competing for the same query. Consolidate or canonicalize.",
        'INTENT_MISMATCH': "De-optimize blog for this commercial keyword. Strengthen the correct page.",
        'GEOGRAPHIC_MISMATCH': "Add unique local evidence to the correct location page. Prune city mentions from wrong page.",
        'PAGE_TYPE_MISMATCH': "Strengthen the category page. De-optimize product page for generic keywords.",
        'HOMEPAGE_HOARDING': "Remove service content from homepage. Add clear link from homepage to service page.",
    }
    
    return recommendations.get(conflict_type, f"Review and resolve {page_count} conflicting pages.")
