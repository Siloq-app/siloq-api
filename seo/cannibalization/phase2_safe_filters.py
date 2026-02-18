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
    
    # FILTER 4: E-commerce category vs product
    if _are_category_vs_product(page_a, page_b):
        return True
    
    # FILTER 5: E-commerce product variants
    if _are_product_variants(page_a, page_b):
        return True
    
    # FILTER 6: Pagination pages
    if _is_pagination_page(page_a) or _is_pagination_page(page_b):
        return True
    
    # FILTER 7: Product tag archives
    if _is_product_tag_archive(page_a) or _is_product_tag_archive(page_b):
        return True
    
    return False


def _are_product_siblings(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    Product sibling filter — spec v2.0 approach.
    
    Pages are product siblings if they share the same parent path and have
    distinct slugs (not legacy variants of each other).
    """
    # Legacy variants are never siblings — they represent the same canonical content
    if page_a.is_legacy_variant or page_b.is_legacy_variant:
        return False

    # Check if pages share a common slug segment
    a_segments = set(page_a.normalized_path.strip('/').split('/'))
    b_segments = set(page_b.normalized_path.strip('/').split('/'))
    shared_segments = a_segments & b_segments
    
    if not shared_segments:
        return False  # No shared URL tokens at all
    
    # Pages must share the same parent path to be siblings
    if page_a.parent_path != page_b.parent_path:
        return False
    
    # Same parent — distinct slugs required (identical slugs = duplicates)
    if page_a.slug_last == page_b.slug_last:
        return False
    
    # Check slug similarity — high similarity means near-duplicates, not siblings
    sim = slug_similarity(page_a.normalized_path, page_b.normalized_path)
    return sim < 0.80


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


def _are_category_vs_product(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    E-commerce filter: Category archives should NOT compete with product pages.
    Different intent: browse (category) vs buy (product).
    
    Criteria:
    - One page is category_woo and the other is product
    - Category is parent or shares parent with product
    """
    # Check if one is category and one is product
    types_set = {page_a.classified_type, page_b.classified_type}
    if types_set != {'category_woo', 'product'}:
        return False
    
    # Identify which is which
    category_page = page_a if page_a.classified_type == 'category_woo' else page_b
    product_page = page_b if page_a.classified_type == 'category_woo' else page_a
    
    # Check if category is parent of product
    if is_direct_parent(category_page.normalized_path, product_page.normalized_path):
        return True
    
    # Check if they share the same parent category
    if category_page.parent_path and product_page.parent_path:
        if category_page.parent_path == product_page.parent_path:
            return True
    
    return False


def _are_product_variants(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    E-commerce filter: Product variants (color/size) should not be flagged as competing.
    
    Criteria:
    - Both are products
    - Share significant slug similarity (same base product)
    - Titles differ by variant indicators (color, size, etc.)
    """
    from .constants import ECOMMERCE_PRODUCT_VARIANT_INDICATORS
    
    # Must both be products
    if page_a.classified_type != 'product' or page_b.classified_type != 'product':
        return False
    
    # Check if they share the same parent path (same product family)
    if page_a.parent_path != page_b.parent_path:
        return False
    
    # Check slug similarity - variants should have high similarity
    sim = slug_similarity(page_a.normalized_path, page_b.normalized_path)
    if sim < 0.70:  # Need at least 70% similarity
        return False
    
    # Check if titles contain variant indicators
    a_title_lower = page_a.title.lower()
    b_title_lower = page_b.title.lower()
    
    # Look for variant indicators in either title
    has_variant_indicator = False
    for indicator in ECOMMERCE_PRODUCT_VARIANT_INDICATORS:
        if indicator in a_title_lower or indicator in b_title_lower:
            has_variant_indicator = True
            break
    
    # Alternative: check if slugs differ by variant-like suffixes
    # e.g., /product-red/ vs /product-blue/
    a_slug = page_a.slug_last.lower()
    b_slug = page_b.slug_last.lower()
    
    # Extract potential variant suffixes (last token after dash)
    a_tokens = a_slug.split('-')
    b_tokens = b_slug.split('-')
    
    if len(a_tokens) == len(b_tokens) and len(a_tokens) > 1:
        # Same structure, check if only last token differs
        if a_tokens[:-1] == b_tokens[:-1] and a_tokens[-1] != b_tokens[-1]:
            return True
    
    return has_variant_indicator


def _is_pagination_page(page: PageClassification) -> bool:
    """
    E-commerce filter: Pagination pages should be excluded from cannibalization.
    
    Criteria:
    - Path matches /page/2/, /page/3/, etc.
    - OR classified_type is 'pagination'
    """
    import re
    from .constants import ECOMMERCE_PAGINATION_PATTERN
    
    # Check if classified as pagination
    if page.classified_type == 'pagination':
        return True
    
    # Check path pattern
    if re.search(ECOMMERCE_PAGINATION_PATTERN, page.normalized_path):
        return True
    
    return False


def _is_product_tag_archive(page: PageClassification) -> bool:
    """
    E-commerce filter: Product tag archives should be excluded or treated as low priority.
    
    Criteria:
    - classified_type is 'product_tag'
    - OR folder_root is 'product-tag'
    """
    if page.classified_type == 'product_tag':
        return True
    
    if page.folder_root == 'product-tag':
        return True
    
    return False
