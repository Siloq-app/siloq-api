"""
Phase 2: Safe Filters

Identifies page pairs that should NOT be flagged as cannibalization:
1. Product siblings (same parent, distinct products)
2. Parent-child relationships (hub → spoke)
3. Geographic variants (same service, different cities)

Returns a set of "safe pairs" (frozenset tuples) that Phase 3 will skip.
"""
from typing import Set, FrozenSet
from .models import PageClassification
from .utils import (
    normalize_geo,
    is_direct_parent,
    has_distinct_subtopic,
    slug_similarity,
    is_legacy_variant,
)


def run_phase2(classifications: list) -> Set[FrozenSet[int]]:
    """
    Phase 2: Build safe_pairs set.
    
    Returns:
        Set of frozenset pairs: {frozenset({page_id_1, page_id_2}), ...}
    """
    safe_pairs = set()
    
    # Build lookup by page_id
    page_by_id = {pc.page_id: pc for pc in classifications}
    
    # Convert to list for pairwise comparison
    page_ids = list(page_by_id.keys())
    
    for i in range(len(page_ids)):
        for j in range(i + 1, len(page_ids)):
            page_a = page_by_id[page_ids[i]]
            page_b = page_by_id[page_ids[j]]
            
            if _is_safe_pair(page_a, page_b):
                safe_pairs.add(frozenset({page_a.page_id, page_b.page_id}))
    
    return safe_pairs


def _is_safe_pair(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    Check if two pages form a safe pair (should not be flagged).
    """
    # FILTER 1: Product siblings
    if _are_product_siblings(page_a, page_b):
        return True
    
    # FILTER 2: Parent-child relationship
    if _are_parent_child(page_a, page_b):
        return True
    
    # FILTER 3: Geographic variants
    if _are_geographic_variants(page_a, page_b):
        return True
    
    return False


def _are_product_siblings(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    Product sibling filter.
    
    Criteria for SAME parent (existing logic):
    - Both classified_type == "product"
    - Same parent_path
    - Distinct slug_last (different product names)
    - NOT legacy variants of each other
    - NOT near-duplicate slugs (Jaccard < 0.80)
    
    NEW: Criteria for DIFFERENT parent (the "cheer" case):
    - Share a common slug token
    - DIFFERENT parent_path
    - Different title keywords (excluding the shared slug)
    - Example: /team-warmups/cheer vs /uniforms/cheer
      → Shared token: "cheer"
      → Different parents: "team-warmups" vs "uniforms"
      → These are cross-linking opportunities, NOT conflicts
    """
    # Must both be products
    if page_a.classified_type != 'product' or page_b.classified_type != 'product':
        return False
    
    # Case 1: SAME parent path (original logic)
    if page_a.parent_path == page_b.parent_path:
        # Must have distinct slugs
        if page_a.slug_last == page_b.slug_last:
            return False
        
        # Must NOT be legacy variants of each other
        if page_a.is_legacy_variant or page_b.is_legacy_variant:
            # Check if one is legacy variant of the other
            if _is_legacy_pair(page_a.normalized_path, page_b.normalized_path):
                return False
        
        # Must NOT be near-duplicate slugs
        similarity = slug_similarity(page_a.normalized_path, page_b.normalized_path)
        if similarity >= 0.80:
            return False
        
        return True
    
    # Case 2: DIFFERENT parent path (NEW logic for "cheer" case)
    else:
        # Check if they share a common slug token
        tokens_a = set(page_a.slug_tokens_json) if page_a.slug_tokens_json else set()
        tokens_b = set(page_b.slug_tokens_json) if page_b.slug_tokens_json else set()
        
        shared_tokens = tokens_a & tokens_b
        if not shared_tokens:
            return False  # No shared tokens, not siblings
        
        # Extract parent folder names (last segment of parent_path)
        parent_a = page_a.parent_path.strip('/').split('/')[-1] if page_a.parent_path else ''
        parent_b = page_b.parent_path.strip('/').split('/')[-1] if page_b.parent_path else ''
        
        # Parents must be different AND distinct (not just modifiers)
        if not parent_a or not parent_b or parent_a == parent_b:
            return False
        
        # Check if parents represent different product categories
        # Extract keywords from titles (excluding shared slug tokens)
        title_a_words = set(page_a.title.lower().split()) - shared_tokens
        title_b_words = set(page_b.title.lower().split()) - shared_tokens
        
        # If title keywords are mostly different (< 50% overlap), they're siblings
        if title_a_words and title_b_words:
            overlap = len(title_a_words & title_b_words) / max(len(title_a_words), len(title_b_words))
            if overlap < 0.50:
                return True  # Different product categories, safe pair
        
        return False


def _are_parent_child(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    Parent-child relationship filter.
    
    Criteria:
    - One path is direct parent of the other
    - Child has distinct subtopic slug (not just a modifier)
    """
    # Check if A is parent of B
    if is_direct_parent(page_a.normalized_path, page_b.normalized_path):
        if has_distinct_subtopic(page_b.normalized_path, page_a.normalized_path):
            return True
    
    # Check if B is parent of A
    if is_direct_parent(page_b.normalized_path, page_a.normalized_path):
        if has_distinct_subtopic(page_a.normalized_path, page_b.normalized_path):
            return True
    
    return False


def _are_geographic_variants(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    Geographic variant filter.
    
    Criteria:
    - Both classified_type == "location"
    - Different geo_node (after normalization)
    """
    # Must both be location pages
    if page_a.classified_type != 'location' or page_b.classified_type != 'location':
        return False
    
    # Must have geo nodes
    if not page_a.geo_node or not page_b.geo_node:
        return False
    
    # Normalize and compare
    geo_a = normalize_geo(page_a.geo_node)
    geo_b = normalize_geo(page_b.geo_node)
    
    # Must be different cities
    if geo_a == geo_b:
        return False
    
    return True


def _is_legacy_pair(path_a: str, path_b: str) -> bool:
    """
    Check if one path is a legacy variant of the other.
    
    Example:
        /service-planning/ and /service-planning-old/ → True
    """
    from .utils import strip_legacy_suffix
    
    # Strip legacy suffixes from both
    clean_a = strip_legacy_suffix(path_a)
    clean_b = strip_legacy_suffix(path_b)
    
    # If they resolve to the same clean path, they're legacy pairs
    return clean_a == clean_b and path_a != path_b
