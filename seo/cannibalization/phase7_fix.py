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


# Page type hierarchy for winner selection (spec v2.0)
PAGE_TYPE_RANK = {
    'category': 6,
    'service': 5,
    'product': 4,
    'location': 3,
    'blog': 2,
    'landing': 1,
    'homepage': 0,  # Never wins service/product conflicts
    'other': 1,
}


def _calculate_winner_score(page, gsc_data_for_page=None):
    """
    Calculate winner score using the spec's priority chain (Spec v2.0 §Winner Selection).
    Returns a tuple for lexicographic comparison (higher = better).
    
    Priority chain:
    1. GSC PERFORMANCE (highest priority):
       - Page with highest clicks wins
       - If clicks tied → highest impressions wins
       - If impressions tied → best (lowest) average position wins
    
    2. PAGE TYPE (tiebreaker when GSC is equal or zero):
       - Service/Product page beats Blog post
       - Category page beats Product page
       - Any page with content beats a thin page
    
    3. CONTENT DEPTH (tiebreaker when page types equal):
       - Higher word count wins
       - More internal links pointing to it wins
    
    4. URL DEPTH (last resort):
       - Shallower URL wins (fewer path segments)
    
    ABSOLUTE RULES:
    - A page with 0 impressions AND 0 clicks NEVER wins over a page with ANY impressions or clicks
    - The homepage NEVER wins a service/product keyword conflict (enforced after selection)
    """
    clicks = gsc_data_for_page.get('clicks', 0) if gsc_data_for_page else 0
    impressions = gsc_data_for_page.get('impressions', 0) if gsc_data_for_page else 0
    position = gsc_data_for_page.get('position', 999) if gsc_data_for_page else 999
    
    # Priority 1: GSC performance
    # Binary flag: has ANY GSC signal (clicks > 0 OR impressions > 0)
    has_gsc_signal = 1 if (clicks > 0 or impressions > 0) else 0
    
    # Priority 2: Page type rank
    page_type = getattr(page, 'classified_type', 'other')
    type_rank = PAGE_TYPE_RANK.get(page_type, 1)
    
    # Priority 3: Content depth
    # Note: word_count might not be on PageClassification yet — using getattr with default
    # TODO: Enhance Phase 1 to populate word_count from PageMetadata or SEOData
    word_count = getattr(page, 'word_count', 0)
    
    # Internal links in (from PageMetadata.internal_links_in if available)
    internal_links_in = getattr(page, 'internal_links_in', 0)
    
    # Priority 4: URL depth (inverted — fewer segments = better)
    # Use depth field if available, otherwise calculate from normalized_path
    if hasattr(page, 'depth') and page.depth is not None:
        path_depth = page.depth
    else:
        path_depth = len(page.normalized_path.strip('/').split('/')) if page.normalized_path else 99
    url_depth_score = 100 - min(path_depth, 100)
    
    # Return tuple for lexicographic comparison
    return (
        has_gsc_signal,      # Binary: has ANY GSC data (0 or 1)
        clicks,              # Raw clicks
        impressions,         # Raw impressions
        -position,           # Negative position (lower position = better, so negate)
        type_rank,           # Page type hierarchy (category > service > product > blog)
        word_count,          # Content depth (word count)
        internal_links_in,   # Internal link authority
        url_depth_score,     # URL depth (shallower = better)
    )


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
    
    # GSC_CONFIRMED: Suggest winner based on complete priority chain
    elif cluster['conflict_type'] == 'GSC_CONFIRMED':
        canonical = _suggest_gsc_winner(pages, cluster)
        if canonical:
            for page in pages:
                if page.page_id != canonical.page_id:
                    redirects.append({
                        'source_url': page.url,
                        'target_url': canonical.url,
                        'confidence': 'high',
                        'reason': 'GSC winner (priority chain: clicks → impressions → position → page type → content depth → URL depth)',
                    })
    
    # DE_OPTIMIZE_HOMEPAGE / HOMEPAGE_DEOPTIMIZE:
    # No 301 redirects — de-optimize homepage content and strengthen service page.
    # DE_OPTIMIZE_HOMEPAGE is the canonical action code for HOMEPAGE_CANNIBALIZATION.
    # HOMEPAGE_DEOPTIMIZE is kept as a legacy alias.
    elif action_code in ('DE_OPTIMIZE_HOMEPAGE', 'HOMEPAGE_DEOPTIMIZE'):
        # Find the homepage and service pages
        homepage = None
        service_pages = []
        for page in pages:
            if page.classified_type == 'homepage':
                homepage = page
            else:
                service_pages.append(page)

        if homepage and service_pages:
            # Pull per-keyword detail from gsc_data when available
            gsc_data = cluster.get('gsc_data', {})
            queries = gsc_data.get('queries', [])

            if queries:
                kw_list = ', '.join(repr(q) for q in queries[:5])
                kw_suffix = f' (and {len(queries) - 5} more)' if len(queries) > 5 else ''
                reason = (
                    f'DE-OPTIMIZE homepage for keyword(s): {kw_list}{kw_suffix}. '
                    f'Strip each keyword from homepage title tag, H1, meta description, and body copy. '
                    f'Homepage should target ONLY [Brand Name] + broad category. '
                    f'Strengthen {service_pages[0].url} — improve its title, meta, H1, and body to '
                    f'clearly own these keywords. Add prominent internal link from homepage to service page.'
                )
            else:
                reason = (
                    f'DE-OPTIMIZE homepage for service keyword. '
                    f'Strip keyword from title tag, H1, meta description, and body content. '
                    f'Homepage should target only [Brand Name] + [broad category]. '
                    f'Strengthen {service_pages[0].url} with internal links from homepage. '
                    'ABSOLUTE RULE: Homepage NEVER wins a service/product keyword conflict.'
                )

            redirects.append({
                'source_url': homepage.url,
                'target_url': service_pages[0].url,
                'confidence': 'high',
                'reason': reason,
            })
    
    # SLUG_PIVOT: Recommend URL change + 301 from old to new
    elif action_code == 'SLUG_PIVOT':
        # The spoke page needs a slug change to reinforce its new keyword angle
        # Actual slug recommendation comes from AI spoke_rewrite
        for page in pages[1:]:  # Skip the hub (pages[0])
            redirects.append({
                'source_url': page.url,
                'target_url': f'{page.url} → [AI-recommended new slug]',
                'confidence': 'medium',
                'reason': 'Slug pivot: URL tokens overlap with hub. Spoke rewrite will recommend new slug that reinforces the differentiated keyword angle. Old URL gets 301 to new.',
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
    Uses the complete priority chain from spec v2.0.
    """
    if not pages:
        return None
    
    # Build URL → GSC metrics lookup
    gsc_lookup = {}
    gsc_data = cluster.get('gsc_data', {})
    if gsc_data and 'gsc_rows' in gsc_data:
        for row in gsc_data['gsc_rows']:
            url = row.get('normalized_url', '')
            gsc_lookup[url] = {
                'clicks': row.get('clicks', 0),
                'impressions': row.get('impressions', 0),
                'position': row.get('position', 999),
            }
    
    # Calculate scores for all pages
    page_scores = []
    for page in pages:
        gsc_data_for_page = gsc_lookup.get(page.normalized_url)
        score = _calculate_winner_score(page, gsc_data_for_page)
        page_scores.append((page, score))
    
    # Sort by score (descending)
    page_scores.sort(key=lambda x: x[1], reverse=True)
    
    # Check if all pages have 0 GSC signals (needs manual review)
    if all(score[0] == 0 for score in [s[1] for s in page_scores]):
        # Flag this cluster for manual review in the parent function
        cluster['needs_manual_review'] = True
    
    # Select winner
    winner = page_scores[0][0] if page_scores else None
    
    # ABSOLUTE RULE: Homepage never wins service/product conflicts
    if winner and winner.classified_type == 'homepage':
        service_pages = [p for p in pages if p.classified_type in ('service', 'product', 'category')]
        if service_pages:
            # Recalculate winner from service/product/category pages only
            service_scores = [(p, s) for p, s in page_scores if p.classified_type in ('service', 'product', 'category')]
            if service_scores:
                winner = service_scores[0][0]
    
    return winner


def _suggest_gsc_winner(pages: list, cluster: Dict) -> Optional:
    """
    Suggest winner based on GSC traffic using the complete priority chain.
    This is the primary winner selection function for GSC_CONFIRMED conflicts.
    """
    gsc_data = cluster.get('gsc_data', {})
    if not gsc_data or 'gsc_rows' not in gsc_data:
        # Fallback to canonical selection if no GSC data
        return _suggest_canonical(pages, cluster)
    
    # Build URL → GSC metrics lookup
    gsc_lookup = {}
    for row in gsc_data['gsc_rows']:
        url = row.get('normalized_url', '')
        gsc_lookup[url] = {
            'clicks': row.get('clicks', 0),
            'impressions': row.get('impressions', 0),
            'position': row.get('position', 999),
        }
    
    # Calculate scores for all pages
    page_scores = []
    for page in pages:
        gsc_data_for_page = gsc_lookup.get(page.normalized_url)
        score = _calculate_winner_score(page, gsc_data_for_page)
        page_scores.append((page, score))
    
    # Sort by score (descending)
    page_scores.sort(key=lambda x: x[1], reverse=True)
    
    # Check if all pages have 0 GSC signals (needs manual review)
    if all(score[0] == 0 for score in [s[1] for s in page_scores]):
        # Flag this cluster for manual review
        cluster['needs_manual_review'] = True
    
    # Select winner
    winner = page_scores[0][0] if page_scores else None
    
    # ABSOLUTE RULE: Homepage never wins service/product conflicts
    if winner and winner.classified_type == 'homepage':
        service_pages = [p for p in pages if p.classified_type in ('service', 'product', 'category')]
        if service_pages:
            # Recalculate winner from service/product/category pages only
            service_scores = [(p, s) for p, s in page_scores if p.classified_type in ('service', 'product', 'category')]
            if service_scores:
                winner = service_scores[0][0]
    
    return winner


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
