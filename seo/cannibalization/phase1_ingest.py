"""
Phase 1: Ingest and Classify

Loads pages from the database, normalizes URLs, and classifies each page type.
This phase does NOT re-crawl WordPress - it uses already-synced Page objects.

Classification priority (first match wins):
1. homepage (path is / or empty)
2. location (path starts with location folders)
3. blog (path contains blog folders or date pattern)
4. product (WooCommerce post_type='product')
5. category_woo (WooCommerce post_type='product_cat')
6. shop_root (depth 1, folder_root='shop')
7. category_shop (depth 2, folder_root='shop')
8. product (depth 3+, folder_root='shop')
9. product_index (path ends with /products/)
10. category_custom (depth 2, folder_root in product_rentals/custom)
11. product (depth 3+, folder_root in product_rentals/custom)
12. service_hub (service folder, depth 1)
13. service_spoke (service folder, depth 2+)
14. portfolio (portfolio folder)
15. utility (cart, checkout, account, wp-admin)
16. uncategorized (fallback)

Legacy detection is a BOOLEAN FLAG, not a page type.
"""
from typing import List, Dict, Optional
from seo.models import Page
from .models import PageClassification
from .utils import (
    normalize_full_url,
    normalize_path,
    get_path_parts,
    get_folder_root,
    get_parent_path,
    get_slug_last,
    extract_slug_tokens,
    is_legacy_variant,
    extract_geo_node,
    extract_service_keyword,
)
from .constants import FOLDER_ROOTS


def run_phase1(analysis_run, site) -> List[PageClassification]:
    """
    Phase 1: Load pages from DB, normalize, and classify.
    
    Returns:
        List of PageClassification objects (saved to DB)
    """
    # Load all published pages (exclude drafts, private, noindex)
    pages = Page.objects.filter(
        site=site,
        status='publish'
    ).exclude(
        is_noindex=True
    )
    
    classifications = []
    
    for page in pages:
        classification = classify_page(analysis_run, site, page)
        if classification:
            classifications.append(classification)
    
    # Bulk create for performance
    PageClassification.objects.bulk_create(classifications)
    
    return classifications


def classify_page(analysis_run, site, page: Page) -> Optional[PageClassification]:
    """
    Classify a single page and return PageClassification object.
    """
    url = page.url
    if not url:
        return None
    
    # Normalize URLs
    normalized_url = normalize_full_url(url)
    normalized_path = normalize_path(url)
    
    # Extract metadata
    parts = get_path_parts(normalized_path)
    depth = len(parts)
    folder_root = get_folder_root(normalized_path)
    parent_path = get_parent_path(normalized_path)
    slug_last = get_slug_last(normalized_path)
    slug_tokens = list(extract_slug_tokens(normalized_path, remove_stop_words=True))
    
    # Classify page type
    classified_type = _classify_page_type(
        normalized_path,
        parts,
        depth,
        folder_root,
        page.post_type if hasattr(page, 'post_type') else None,
        page.is_homepage if hasattr(page, 'is_homepage') else False
    )
    
    # Detect legacy variant (boolean flag, not a type)
    is_legacy = is_legacy_variant(normalized_path)
    
    # Extract geo node (for location pages)
    geo_node = ''
    if classified_type == 'location':
        geo_node = extract_geo_node(normalized_path) or ''
    
    # Extract service keyword
    service_kw = extract_service_keyword(normalized_path) or ''
    
    classification = PageClassification(
        analysis_run=analysis_run,
        site=site,
        page_id=page.id,
        url=url,
        title=page.title or '',
        normalized_url=normalized_url,
        normalized_path=normalized_path,
        classified_type=classified_type,
        is_legacy_variant=is_legacy,
        folder_root=folder_root,
        parent_path=parent_path,
        slug_last=slug_last,
        depth=depth,
        geo_node=geo_node,
        service_keyword=service_kw,
        slug_tokens_json=slug_tokens,
    )
    
    return classification


def _classify_page_type(
    path: str,
    parts: List[str],
    depth: int,
    folder_root: str,
    post_type: Optional[str],
    is_homepage_flag: bool
) -> str:
    """
    Classify page type using priority-ordered rules.
    First match wins.
    """
    # RULE 1: Homepage
    if path == '/' or is_homepage_flag:
        return 'homepage'
    
    # RULE 2: Location pages
    if folder_root in FOLDER_ROOTS['location']:
        return 'location'
    
    # RULE 3: Blog posts
    # Check for date pattern: /2024/02/post-title/
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        return 'blog'
    # Check blog folders
    if folder_root in FOLDER_ROOTS['blog']:
        return 'blog'
    
    # RULE 4: WooCommerce product (from post_type)
    if post_type == 'product':
        return 'product'
    
    # RULE 5: WooCommerce category (from post_type)
    if post_type in ['product_cat', 'product_category']:
        return 'category_woo'
    
    # RULE 6: Shop root (depth 1)
    if folder_root == 'shop' and depth == 1:
        return 'shop_root'
    
    # RULE 7: Shop category (depth 2)
    if folder_root == 'shop' and depth == 2:
        return 'category_shop'
    
    # RULE 8: Shop product (depth 3+)
    if folder_root == 'shop' and depth >= 3:
        return 'product'
    
    # RULE 9: Product index page (/products/)
    if parts and parts[-1] in ['products', 'items']:
        return 'product_index'
    
    # RULE 10: Product-category (depth 3+ after /product-category/)
    if folder_root == 'product-category':
        if depth >= 3:
            return 'product'  # Changed from v2.0: depth 3+ is subcategory, NOT product
        else:
            return 'category_woo'
    
    # RULE 11: Custom product rentals category (depth 2)
    if folder_root in FOLDER_ROOTS['product_rentals'] and depth == 2:
        return 'category_custom'
    
    # RULE 12: Custom product rentals product (depth 3+)
    if folder_root in FOLDER_ROOTS['product_rentals'] and depth >= 3:
        return 'product'
    
    # RULE 13: Service hub (depth 1)
    if folder_root in FOLDER_ROOTS['service'] and depth == 1:
        return 'service_hub'
    
    # RULE 14: Service spoke (depth 2+)
    if folder_root in FOLDER_ROOTS['service'] and depth >= 2:
        return 'service_spoke'
    
    # RULE 15: Portfolio
    if folder_root in FOLDER_ROOTS['portfolio']:
        return 'portfolio'
    
    # RULE 16: Utility pages
    if folder_root in FOLDER_ROOTS['utility']:
        return 'utility'
    
    # RULE 17: Fallback
    return 'uncategorized'
