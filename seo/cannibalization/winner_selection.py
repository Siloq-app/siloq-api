"""
Winner Selection Utility for Cannibalization Conflicts

This module provides the canonical winner selection logic that should be used
anywhere ConflictPage.winner_score and is_recommended_winner need to be set.

Implements the complete priority chain from Siloq Cannibalization Engine Spec v2.0.
"""


# Page type hierarchy for winner selection (spec v2.0)
PAGE_TYPE_RANK = {
    'category': 6,
    'category_woo': 6,
    'category_shop': 6,
    'service': 5,
    'service_hub': 5,
    'service_spoke': 5,
    'product': 4,
    'location': 3,
    'blog': 2,
    'landing': 1,
    'homepage': 0,  # Never wins service/product conflicts
    'other': 1,
}


def calculate_winner_score_for_conflict_page(page_data: dict) -> float:
    """
    Calculate winner score for a ConflictPage object.
    
    Args:
        page_data: Dict with keys:
            - gsc_clicks (int)
            - gsc_impressions (int)
            - gsc_avg_position (float)
            - page_type (str)
            - word_count (int, optional)
            - backlink_count (int, optional)
            - internal_links_in (int, optional)
            - page_url (str, for URL depth calculation)
    
    Returns:
        float: Winner score (higher = better winner candidate)
    
    The score is a composite that encodes the priority chain:
    - 10M range: has_gsc_signal (0 or 10,000,000)
    - 1M range: clicks (up to 999,999)
    - 1K range: impressions (scaled)
    - 100 range: position (inverted, scaled)
    - 10 range: page type rank
    - 1 range: content depth + URL depth (fractional)
    """
    clicks = page_data.get('gsc_clicks', 0)
    impressions = page_data.get('gsc_impressions', 0)
    position = page_data.get('gsc_avg_position', 999)
    page_type = page_data.get('page_type', 'other')
    word_count = page_data.get('word_count', 0)
    backlink_count = page_data.get('backlink_count', 0)
    internal_links_in = page_data.get('internal_links_in', 0)
    page_url = page_data.get('page_url', '')
    
    # Priority 1: GSC signal (binary - either you have it or you don't)
    has_gsc_signal = 10_000_000 if (clicks > 0 or impressions > 0) else 0
    
    # Priority 2: Clicks (capped at 999,999)
    clicks_score = min(clicks, 999_999) * 1000
    
    # Priority 3: Impressions (scaled to 1-999 range)
    impressions_score = min(impressions, 999_999) / 1000
    
    # Priority 4: Position (inverted - lower is better, scaled to 0-99)
    position_score = max(0, 100 - position)
    
    # Priority 5: Page type rank (0-6)
    type_rank = PAGE_TYPE_RANK.get(page_type, 1) * 10
    
    # Priority 6: Content depth (word count scaled, plus backlinks and internal links)
    # Scale word count to 0-1 range (assuming 5000 words is "perfect")
    content_score = min(word_count / 5000, 1) * 0.5
    # Add backlink authority (scaled to 0-0.25)
    content_score += min(backlink_count / 100, 1) * 0.25
    # Add internal link authority (scaled to 0-0.15)
    content_score += min(internal_links_in / 50, 1) * 0.15
    
    # Priority 7: URL depth (shallower = better)
    # Calculate depth from URL path
    if page_url:
        # Remove protocol and domain, count path segments
        path = page_url.split('//', 1)[-1]  # Remove protocol
        path = '/'.join(path.split('/')[1:])  # Remove domain
        depth = len([p for p in path.split('/') if p])
        # Invert: shallower = better, scaled to 0-0.1
        url_depth_score = max(0, 1 - (depth / 10)) * 0.1
    else:
        url_depth_score = 0
    
    # Combine all scores
    total_score = (
        has_gsc_signal +
        clicks_score +
        impressions_score +
        position_score +
        type_rank +
        content_score +
        url_depth_score
    )
    
    return round(total_score, 1)


def select_recommended_winner(pages_data: list) -> dict:
    """
    Select the recommended winner from a list of conflicting pages.
    
    Args:
        pages_data: List of dicts, each containing page data for calculate_winner_score_for_conflict_page()
    
    Returns:
        Dict with keys:
            - winner_index: int (index of winning page in pages_data)
            - winner_score: float
            - all_scores: list of (index, score) tuples
            - needs_manual_review: bool (True if all pages have 0 GSC signals)
            - homepage_override: bool (True if homepage was initially winner but overridden)
    """
    if not pages_data:
        return {
            'winner_index': None,
            'winner_score': 0,
            'all_scores': [],
            'needs_manual_review': True,
            'homepage_override': False,
        }
    
    # Calculate scores for all pages
    scores = [(i, calculate_winner_score_for_conflict_page(page)) for i, page in enumerate(pages_data)]
    
    # Sort by score descending
    scores.sort(key=lambda x: x[1], reverse=True)
    
    # Check if all pages have 0 GSC signals (score < 1M means no GSC signal)
    all_zero_gsc = all(score < 1_000_000 for _, score in scores)
    
    # Select initial winner
    winner_index, winner_score = scores[0]
    winner_page = pages_data[winner_index]
    
    # ABSOLUTE RULE: Homepage never wins service/product conflicts
    homepage_override = False
    if winner_page.get('page_type') == 'homepage':
        # Check if there are service/product/category pages in the conflict
        service_pages = [
            (i, score) for i, score in scores
            if pages_data[i].get('page_type') in ('service', 'service_hub', 'service_spoke', 'product', 'category', 'category_woo', 'category_shop')
        ]
        
        if service_pages:
            # Override winner with highest-scoring service/product/category page
            winner_index, winner_score = service_pages[0]
            homepage_override = True
    
    return {
        'winner_index': winner_index,
        'winner_score': winner_score,
        'all_scores': scores,
        'needs_manual_review': all_zero_gsc,
        'homepage_override': homepage_override,
    }


def apply_winner_selection_to_conflict_pages(conflict_pages: list) -> list:
    """
    Apply winner selection to a list of ConflictPage model instances.
    Modifies the objects in place (sets winner_score and is_recommended_winner).
    
    Args:
        conflict_pages: List of ConflictPage model instances
    
    Returns:
        List of modified ConflictPage instances (for chaining)
    """
    # Build page data for selection
    pages_data = []
    for cp in conflict_pages:
        pages_data.append({
            'gsc_clicks': cp.gsc_clicks,
            'gsc_impressions': cp.gsc_impressions,
            'gsc_avg_position': float(cp.gsc_avg_position) if cp.gsc_avg_position else 999,
            'page_type': cp.page_type,
            'backlink_count': cp.backlink_count,
            'page_url': cp.page_url,
            # Note: word_count and internal_links_in not on ConflictPage model yet
            # 'word_count': getattr(cp, 'word_count', 0),
            # 'internal_links_in': getattr(cp, 'internal_links_in', 0),
        })
    
    # Select winner
    result = select_recommended_winner(pages_data)
    
    # Apply winner scores and flag
    for i, cp in enumerate(conflict_pages):
        # Find this page's score in all_scores
        score = next((s for idx, s in result['all_scores'] if idx == i), 0)
        cp.winner_score = score
        cp.is_recommended_winner = (i == result['winner_index'])
    
    return conflict_pages
