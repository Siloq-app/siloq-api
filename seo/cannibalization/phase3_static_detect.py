"""
Phase 3: Static Detection

Detects potential cannibalization from URL/content patterns (NO GSC data yet).

Conflict types detected:
- TAXONOMY_CLASH: Same slug in different folder structures
- LEGACY_CLEANUP: Legacy variant with clean version available
- LEGACY_ORPHAN: Legacy variant with no clean version
- NEAR_DUPLICATE_CONTENT: >80% slug token similarity
- CONTEXT_DUPLICATE: Same service slug under different parent paths
- LOCATION_BOILERPLATE: 3+ location pages with identical title template

All conflicts get:
- badge='POTENTIAL' (not GSC-validated yet)
- bucket='SITE_DUPLICATION'
"""
from typing import List, Dict, Set, FrozenSet
from collections import defaultdict
from .models import PageClassification
from .utils import (
    slug_similarity,
    strip_legacy_suffix,
    extract_title_template,
)
from .constants import CONFLICT_TYPES


# Import helper to check product siblings
def _are_product_siblings_check(page_a: PageClassification, page_b: PageClassification) -> bool:
    """
    Check if two pages are product siblings (spec v2.0).
    Copied from phase2_safe_filters to avoid circular import.
    """
    STOP_WORDS = {'the', 'a', 'an', 'and', 'or', 'for', 'in', 'on', 'at', 'to', 'of', 'is', 'it', 'by', 'with'}
    
    # Check if pages share a common slug segment
    a_segments = set(page_a.normalized_path.strip('/').split('/'))
    b_segments = set(page_b.normalized_path.strip('/').split('/'))
    shared_segments = a_segments & b_segments
    
    if not shared_segments:
        return False
    
    # Same parent — use existing logic
    if page_a.parent_path == page_b.parent_path:
        if page_a.slug_last == page_b.slug_last:
            return False
        sim = slug_similarity(page_a.normalized_path, page_b.normalized_path)
        return sim < 0.80
    
    # Different parent paths — check titles for distinct products
    shared_tokens = set()
    for seg in shared_segments:
        shared_tokens.update(seg.lower().split('-'))
    
    a_title_tokens = set(page_a.title.lower().split()) - shared_tokens - STOP_WORDS
    b_title_tokens = set(page_b.title.lower().split()) - shared_tokens - STOP_WORDS
    
    if a_title_tokens and b_title_tokens:
        overlap = a_title_tokens & b_title_tokens
        union = a_title_tokens | b_title_tokens
        if len(union) > 0 and len(overlap) / len(union) < 0.5:
            return True
    
    return False


def run_phase3(
    classifications: List[PageClassification],
    safe_pairs: Set[FrozenSet[int]]
) -> List[Dict]:
    """
    Phase 3: Detect static cannibalization issues.
    
    Returns:
        List of issue dicts with structure:
        {
            'conflict_type': str,
            'severity': str,
            'pages': list[PageClassification],
            'metadata': dict,  # type-specific data
        }
    """
    issues = []
    
    # Detection 1: TAXONOMY_CLASH (same slug in different folders)
    issues.extend(_detect_taxonomy_clash(classifications, safe_pairs))
    
    # Detection 2: LEGACY variants (with and without clean versions)
    issues.extend(_detect_legacy_variants(classifications, safe_pairs))
    
    # Detection 3: NEAR_DUPLICATE_CONTENT (>80% slug similarity)
    issues.extend(_detect_near_duplicates(classifications, safe_pairs))
    
    # Detection 4: CONTEXT_DUPLICATE (same service under different paths)
    issues.extend(_detect_context_duplicates(classifications, safe_pairs))
    
    # Detection 5: LOCATION_BOILERPLATE (identical title templates)
    issues.extend(_detect_location_boilerplate(classifications, safe_pairs))
    
    return issues


def _detect_taxonomy_clash(
    classifications: List[PageClassification],
    safe_pairs: Set[FrozenSet[int]]
) -> List[Dict]:
    """
    TAXONOMY_CLASH: Same slug_last exists in different folder_roots.
    
    Example:
        /shop/jazz-shoes/
        /product-category/jazz-shoes/
        → Taxonomy clash on "jazz-shoes"
    
    Special case: Product siblings (different parent paths, shared slug token, 
    distinct title keywords) are classified as INFO with cross-linking recommendation.
    """
    issues = []
    
    # Group by slug_last
    slug_groups = defaultdict(list)
    for pc in classifications:
        if pc.slug_last and pc.classified_type not in ['homepage', 'utility']:
            slug_groups[pc.slug_last].append(pc)
    
    # Check each slug group for different folder_roots
    for slug, pages in slug_groups.items():
        if len(pages) < 2:
            continue
        
        # Group by folder_root
        folder_groups = defaultdict(list)
        for page in pages:
            folder_groups[page.folder_root].append(page)
        
        # Must have 2+ different folder roots
        if len(folder_groups) < 2:
            continue
        
        # Check if any pairs are safe
        all_pages = pages
        filtered_pages = []
        for page in all_pages:
            # Check if this page is in a safe pair with any other page in group
            is_safe = False
            for other in all_pages:
                if page.page_id != other.page_id:
                    if frozenset({page.page_id, other.page_id}) in safe_pairs:
                        is_safe = True
                        break
            if not is_safe:
                filtered_pages.append(page)
        
        if len(filtered_pages) >= 2:
            # Before flagging as HIGH conflict, check if these are product siblings
            # with different parent paths (the "cheer" case)
            all_siblings = True
            for i in range(len(filtered_pages)):
                for j in range(i + 1, len(filtered_pages)):
                    if not _are_product_siblings_check(filtered_pages[i], filtered_pages[j]):
                        all_siblings = False
                        break
                if not all_siblings:
                    break
            
            if all_siblings and len(filtered_pages) >= 2:
                # These are product siblings — classify as INFO with cross-linking
                issues.append({
                    'conflict_type': 'PRODUCT_SIBLINGS',
                    'severity': 'INFO',
                    'pages': filtered_pages,
                    'metadata': {
                        'shared_slug': slug,
                        'folder_count': len(folder_groups),
                        'recommendation': 'Add cross-links between related products',
                    },
                })
            else:
                # Normal taxonomy clash — HIGH severity
                issues.append({
                    'conflict_type': 'TAXONOMY_CLASH',
                    'severity': 'HIGH',
                    'pages': filtered_pages,
                    'metadata': {
                        'shared_slug': slug,
                        'folder_count': len(folder_groups),
                    },
                })
    
    return issues


def _detect_legacy_variants(
    classifications: List[PageClassification],
    safe_pairs: Set[FrozenSet[int]]
) -> List[Dict]:
    """
    LEGACY_CLEANUP: Legacy page has clean version.
    LEGACY_ORPHAN: Legacy page without clean version.
    """
    issues = []
    
    # Find all legacy pages
    legacy_pages = [pc for pc in classifications if pc.is_legacy_variant]
    
    # Build lookup by normalized path (strip trailing slashes for consistent matching,
    # since strip_legacy_suffix always returns paths without trailing slash)
    path_lookup = {
        (pc.normalized_path if pc.normalized_path == '/' else pc.normalized_path.rstrip('/')): pc
        for pc in classifications
    }
    
    for legacy_page in legacy_pages:
        # Find the clean version
        clean_path = strip_legacy_suffix(legacy_page.normalized_path)
        clean_page = path_lookup.get(clean_path)
        
        if clean_page and clean_page.page_id != legacy_page.page_id:
            # Check if this is a safe pair
            if frozenset({legacy_page.page_id, clean_page.page_id}) not in safe_pairs:
                issues.append({
                    'conflict_type': 'LEGACY_CLEANUP',
                    'severity': 'HIGH',
                    'pages': [legacy_page, clean_page],
                    'metadata': {
                        'legacy_url': legacy_page.url,
                        'clean_url': clean_page.url,
                    },
                })
        else:
            # Orphan legacy page (no clean version)
            issues.append({
                'conflict_type': 'LEGACY_ORPHAN',
                'severity': 'MEDIUM',
                'pages': [legacy_page],
                'metadata': {
                    'legacy_url': legacy_page.url,
                },
            })
    
    return issues


def _detect_near_duplicates(
    classifications: List[PageClassification],
    safe_pairs: Set[FrozenSet[int]]
) -> List[Dict]:
    """
    NEAR_DUPLICATE_CONTENT: Slug token similarity > 0.80
    """
    issues = []
    
    # Pairwise comparison
    pages = [pc for pc in classifications if pc.classified_type not in ['homepage', 'utility']]
    
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            page_a = pages[i]
            page_b = pages[j]
            
            # Skip safe pairs
            if frozenset({page_a.page_id, page_b.page_id}) in safe_pairs:
                continue
            
            # Check similarity
            similarity = slug_similarity(page_a.normalized_path, page_b.normalized_path)
            
            if similarity > 0.80:
                issues.append({
                    'conflict_type': 'NEAR_DUPLICATE_CONTENT',
                    'severity': 'MEDIUM',
                    'pages': [page_a, page_b],
                    'metadata': {
                        'similarity_score': round(similarity, 2),
                        'slug_pivot_needed': True,
                    },
                    'action_code': 'SLUG_PIVOT',
                })
            elif similarity > 0.60:
                # High slug overlap — URL tokens are sending competing signals
                # Content differentiation alone won't work; slug must pivot too
                issues.append({
                    'conflict_type': 'NEAR_DUPLICATE_CONTENT',
                    'severity': 'LOW',
                    'pages': [page_a, page_b],
                    'metadata': {
                        'similarity_score': round(similarity, 2),
                        'slug_pivot_needed': True,
                    },
                    'action_code': 'SLUG_PIVOT',
                })
    
    return issues


def _detect_context_duplicates(
    classifications: List[PageClassification],
    safe_pairs: Set[FrozenSet[int]]
) -> List[Dict]:
    """
    CONTEXT_DUPLICATE: Same service_keyword under different parent paths.
    
    Example:
        /services/event-planning/
        /residential/event-planning/
        → Same service in different contexts
    """
    issues = []
    
    # Group by service_keyword
    service_groups = defaultdict(list)
    for pc in classifications:
        if pc.service_keyword and pc.classified_type in ['service_hub', 'service_spoke']:
            service_groups[pc.service_keyword].append(pc)
    
    # Check each group for different parent paths
    for service_kw, pages in service_groups.items():
        if len(pages) < 2:
            continue
        
        # Group by parent_path
        parent_groups = defaultdict(list)
        for page in pages:
            parent_groups[page.parent_path].append(page)
        
        # Must have 2+ different parents
        if len(parent_groups) < 2:
            continue
        
        # Check for safe pairs
        all_pages = pages
        filtered_pages = []
        for page in all_pages:
            is_safe = False
            for other in all_pages:
                if page.page_id != other.page_id:
                    if frozenset({page.page_id, other.page_id}) in safe_pairs:
                        is_safe = True
                        break
            if not is_safe:
                filtered_pages.append(page)
        
        if len(filtered_pages) >= 2:
            issues.append({
                'conflict_type': 'CONTEXT_DUPLICATE',
                'severity': 'MEDIUM',
                'pages': filtered_pages,
                'metadata': {
                    'service_keyword': service_kw,
                },
            })
    
    return issues


def _detect_location_boilerplate(
    classifications: List[PageClassification],
    safe_pairs: Set[FrozenSet[int]]
) -> List[Dict]:
    """
    LOCATION_BOILERPLATE: 3+ location pages with identical title template
    (after removing geo_node).
    
    This is NOT a keyword conflict - it's a content quality issue.
    """
    issues = []
    
    # Get all location pages
    location_pages = [pc for pc in classifications if pc.classified_type == 'location']
    
    if len(location_pages) < 3:
        return issues
    
    # Group by title template
    template_groups = defaultdict(list)
    for page in location_pages:
        template = extract_title_template(page.title, page.geo_node)
        if template:
            template_groups[template].append(page)
    
    # Find groups with 3+ pages
    for template, pages in template_groups.items():
        if len(pages) >= 3:
            issues.append({
                'conflict_type': 'LOCATION_BOILERPLATE',
                'severity': 'MEDIUM',
                'pages': pages,
                'metadata': {
                    'title_template': template,
                    'page_count': len(pages),
                },
            })
    
    return issues
