"""
Phase 7: Fix Recommendations

Generates actionable fix recommendations:
- Redirect plan CSV (source → suggested canonical)
- Action codes with user guidance
- Dry run mode (NEVER auto-writes .htaccess)

IMPORTANT: This phase NEVER auto-picks canonical or writes redirects.
All fixes require user review and approval.
"""
from typing import List, Dict, Optional
import csv
import io
from .constants import ACTION_CODES


def run_phase7(clustered_issues: List[Dict], dry_run: bool = True) -> Dict:
    """
    Phase 7: Generate fix recommendations.
    
    Args:
        clustered_issues: Output from Phase 6
        dry_run: If True (default), only suggest fixes (no auto-execution)
    
    Returns:
        {
            'redirect_plan_csv': str,  # CSV content
            'action_summary': dict,     # Counts by action code
            'requires_user_input': list,  # Clusters needing user decisions
        }
    """
    redirect_plan = []
    action_summary = {code: 0 for code in ACTION_CODES.keys()}
    requires_user_input = []
    
    for cluster in clustered_issues:
        action_code = cluster['action_code']
        action_summary[action_code] += 1
        
        # Generate redirect recommendations
        redirects = _generate_redirects(cluster)
        redirect_plan.extend(redirects)
        
        # Track clusters requiring user input
        if ACTION_CODES[action_code]['requires_user_input']:
            requires_user_input.append({
                'cluster_key': cluster['cluster_key'],
                'conflict_type': cluster['conflict_type'],
                'page_count': cluster['page_count'],
                'recommendation': cluster['recommendation'],
            })
    
    # Generate CSV
    csv_content = _generate_redirect_csv(redirect_plan)
    
    return {
        'redirect_plan_csv': csv_content,
        'action_summary': action_summary,
        'requires_user_input': requires_user_input,
        'redirect_count': len(redirect_plan),
    }


def _generate_redirects(cluster: Dict) -> List[Dict]:
    """
    Generate redirect recommendations for a cluster.
    
    Returns list of redirect dicts:
    {
        'source_url': str,
        'target_url': str,
        'confidence': str ('high', 'medium', 'low'),
        'reason': str,
    }
    """
    redirects = []
    action_code = cluster['action_code']
    pages = cluster['pages']
    
    if not pages:
        return redirects
    
    # AUTO-SUGGEST REDIRECTS (user must still approve)
    
    # LEGACY_CLEANUP: Legacy → Clean version
    if cluster['conflict_type'] == 'LEGACY_CLEANUP':
        for page in pages:
            if page.is_legacy_variant:
                # Find non-legacy version
                clean_page = _find_clean_version(page, pages)
                if clean_page:
                    redirects.append({
                        'source_url': page.url,
                        'target_url': clean_page.url,
                        'confidence': 'high',
                        'reason': 'Legacy variant → clean version',
                    })
    
    # TAXONOMY_CLASH: Suggest canonical based on metrics
    elif cluster['conflict_type'] == 'TAXONOMY_CLASH':
        canonical = _suggest_canonical(pages, cluster)
        if canonical:
            for page in pages:
                if page.page_id != canonical.page_id:
                    redirects.append({
                        'source_url': page.url,
                        'target_url': canonical.url,
                        'confidence': 'medium',
                        'reason': 'Taxonomy clash - suggested canonical',
                    })
    
    # NEAR_DUPLICATE_CONTENT: Suggest canonical
    elif cluster['conflict_type'] == 'NEAR_DUPLICATE_CONTENT':
        canonical = _suggest_canonical(pages, cluster)
        if canonical:
            for page in pages:
                if page.page_id != canonical.page_id:
                    redirects.append({
                        'source_url': page.url,
                        'target_url': canonical.url,
                        'confidence': 'medium',
                        'reason': 'Near-duplicate content',
                    })
    
    # GSC_CONFIRMED: Suggest winner based on clicks
    elif cluster['conflict_type'] == 'GSC_CONFIRMED':
        canonical = _suggest_gsc_winner(pages, cluster)
        if canonical:
            for page in pages:
                if page.page_id != canonical.page_id:
                    redirects.append({
                        'source_url': page.url,
                        'target_url': canonical.url,
                        'confidence': 'high',
                        'reason': 'GSC winner (most clicks)',
                    })
    
    # WRONG_WINNER types: No redirects, just strengthen correct page
    # LOCATION_BOILERPLATE: No redirects, rewrite content
    # CONTEXT_DUPLICATE: User must decide merge vs differentiate
    # LEGACY_ORPHAN: User must choose target
    
    return redirects


def _find_clean_version(legacy_page, all_pages: list) -> Optional:
    """Find the clean (non-legacy) version of a legacy page."""
    from .utils import strip_legacy_suffix
    
    clean_path = strip_legacy_suffix(legacy_page.normalized_path)
    
    for page in all_pages:
        if not page.is_legacy_variant and page.normalized_path == clean_path:
            return page
    
    return None


def _suggest_canonical(pages: list, cluster: Dict) -> Optional:
    """
    Suggest canonical page from a set of duplicates.
    
    Criteria (in order):
    1. Most GSC clicks (if GSC data available)
    2. Shortest URL path (simpler = more canonical)
    3. First alphabetically (stable tiebreaker)
    """
    if not pages:
        return None
    
    # Check for GSC data
    gsc_data = cluster.get('gsc_data', {})
    if gsc_data and 'gsc_rows' in gsc_data:
        # Build URL → clicks map
        url_clicks = {}
        for row in gsc_data['gsc_rows']:
            url = row.get('normalized_url', '')
            clicks = row.get('clicks', 0)
            url_clicks[url] = url_clicks.get(url, 0) + clicks
        
        # Find page with most clicks
        best_page = None
        max_clicks = -1
        for page in pages:
            clicks = url_clicks.get(page.normalized_url, 0)
            if clicks > max_clicks:
                max_clicks = clicks
                best_page = page
        
        if best_page and max_clicks > 0:
            return best_page
    
    # Fallback: Shortest URL
    pages_sorted = sorted(pages, key=lambda p: (len(p.normalized_path), p.normalized_path))
    return pages_sorted[0] if pages_sorted else None


def _suggest_gsc_winner(pages: list, cluster: Dict) -> Optional:
    """Suggest winner based on GSC clicks."""
    gsc_data = cluster.get('gsc_data', {})
    if not gsc_data or 'gsc_rows' not in gsc_data:
        return _suggest_canonical(pages, cluster)
    
    # Build URL → clicks map
    url_clicks = {}
    for row in gsc_data['gsc_rows']:
        url = row.get('normalized_url', '')
        clicks = row.get('clicks', 0)
        url_clicks[url] = url_clicks.get(url, 0) + clicks
    
    # Find page with most clicks
    best_page = None
    max_clicks = -1
    for page in pages:
        clicks = url_clicks.get(page.normalized_url, 0)
        if clicks > max_clicks:
            max_clicks = clicks
            best_page = page
    
    return best_page or (pages[0] if pages else None)


def _generate_redirect_csv(redirect_plan: List[Dict]) -> str:
    """
    Generate CSV content for redirect plan.
    
    Columns: Source URL, Target URL, Confidence, Reason
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['Source URL', 'Target URL', 'Confidence', 'Reason', 'Status'])
    
    # Rows
    for redirect in redirect_plan:
        writer.writerow([
            redirect['source_url'],
            redirect['target_url'],
            redirect['confidence'],
            redirect['reason'],
            'pending_review',  # User must approve
        ])
    
    return output.getvalue()


def generate_action_plan(clustered_issues: List[Dict]) -> str:
    """
    Generate human-readable action plan.
    """
    lines = []
    lines.append("# Cannibalization Fix Action Plan\n")
    lines.append(f"Total clusters found: {len(clustered_issues)}\n")
    lines.append("")
    
    # Group by action code
    from collections import defaultdict
    by_action = defaultdict(list)
    for cluster in clustered_issues:
        by_action[cluster['action_code']].append(cluster)
    
    # Output each action type
    for action_code, clusters in by_action.items():
        action_info = ACTION_CODES[action_code]
        lines.append(f"## {action_info['label']} ({len(clusters)} clusters)")
        lines.append(f"**Description:** {action_info['description']}\n")
        
        for cluster in clusters[:5]:  # Show top 5 per action
            lines.append(f"- **{cluster['conflict_type']}**: {cluster['page_count']} pages")
            lines.append(f"  Severity: {cluster['severity']} | Priority: {cluster['priority_score']}")
            lines.append(f"  {cluster['recommendation']}\n")
        
        if len(clusters) > 5:
            lines.append(f"... and {len(clusters) - 5} more\n")
        
        lines.append("")
    
    return '\n'.join(lines)
