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
    Product sibling filter — spec v2.0 approach.
    
    Pages are product siblings if they share a slug token but the 
    non-shared portions of their titles indicate distinct products.
    Works regardless of page type classification.
    """
    # Check if pages share a common slug segment
    a_segments = set(page_a.normalized_path.strip('/').split('/'))
    b_segments = set(page_b.normalized_path.strip('/').split('/'))
    shared_segments = a_segments & b_segments
    
    if not shared_segments:
        return False  # No shared URL tokens at all
    
    # Check if parent paths are DIFFERENT (same parent = old logic still applies)
    # Different parent paths sharing a slug token = likely product siblings
    if page_a.parent_path == page_b.parent_path:
        # Same parent — use existing logic (distinct slugs, not legacy variants)
        if page_a.slug_last == page_b.slug_last:
            return False
        # Check slug similarity
        sim = slug_similarity(page_a.normalized_path, page_b.normalized_path)
        return sim < 0.80
    
    # Different parent paths — check titles for distinct products
    # Strip shared slug tokens from both titles
    shared_tokens = set()
    for seg in shared_segments:
        shared_tokens.update(seg.lower().split('-'))
    
    a_title_tokens = set(page_a.title.lower().split()) - shared_tokens - STOP_WORDS
    b_title_tokens = set(page_b.title.lower().split()) - shared_tokens - STOP_WORDS
    
    # If remaining title tokens are different, these are distinct products
    if a_title_tokens and b_title_tokens:
        overlap = a_title_tokens & b_title_tokens
        union = a_title_tokens | b_title_tokens
        if len(union) > 0 and len(overlap) / len(union) < 0.5:
            return True  # Distinct products
    
    return False


STOP_WORDS = {'the', 'a', 'an', 'and', 'or', 'for', 'in', 'on', 'at', 'to', 'of', 'is', 'it', 'by', 'with'}


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
