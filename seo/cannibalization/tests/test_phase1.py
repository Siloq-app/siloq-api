"""
Test Group A: Phase 1 Classification

Tests URL normalization and page type classification logic.
"""
import pytest
from django.test import TestCase
from unittest.mock import Mock
from seo.cannibalization.phase1_ingest import _classify_page_type
from seo.cannibalization.utils import (
    normalize_full_url,
    normalize_path,
    get_path_parts,
    get_folder_root,
    get_parent_path,
    get_slug_last,
    is_legacy_variant,
    strip_legacy_suffix,
)


class TestNormalization(TestCase):
    """Test URL normalization functions."""
    
    def test_normalize_full_url(self):
        """Test full URL normalization."""
        # Remove protocol, www, query, fragment
        assert normalize_full_url('https://www.example.com/page/?utm=123#section') == 'example.com/page'
        assert normalize_full_url('http://example.com/page/') == 'example.com/page'
        assert normalize_full_url('https://example.com/') == 'example.com'
    
    def test_normalize_path(self):
        """Test path normalization."""
        assert normalize_path('https://example.com/blog/post-title/') == '/blog/post-title'
        assert normalize_path('https://example.com/') == '/'
        assert normalize_path('https://example.com/page/?query=test') == '/page'
    
    def test_get_path_parts(self):
        """Test path part extraction."""
        assert get_path_parts('/product-category/dance/jazz/') == ['product-category', 'dance', 'jazz']
        assert get_path_parts('/') == []
        assert get_path_parts('/single/') == ['single']
    
    def test_get_folder_root(self):
        """Test folder root extraction."""
        assert get_folder_root('/blog/2024/post-title/') == 'blog'
        assert get_folder_root('/product-category/dance/') == 'product-category'
        assert get_folder_root('/') == ''
    
    def test_get_parent_path(self):
        """Test parent path extraction."""
        assert get_parent_path('/shop/clothing/shirts/') == '/shop/clothing'
        assert get_parent_path('/shop/') == '/'
        assert get_parent_path('/') == '/'
    
    def test_get_slug_last(self):
        """Test last slug extraction."""
        assert get_slug_last('/product-category/dance/jazz/') == 'jazz'
        assert get_slug_last('/single-page/') == 'single-page'
        assert get_slug_last('/') == ''


class TestLegacyDetection(TestCase):
    """Test legacy variant detection."""
    
    def test_is_legacy_variant(self):
        """Test legacy suffix detection."""
        assert is_legacy_variant('/page-old/') == True
        assert is_legacy_variant('/service-backup/') == True
        assert is_legacy_variant('/product-2/') == True
        assert is_legacy_variant('/service-area/brooklyn/') == False
        assert is_legacy_variant('/normal-page/') == False
    
    def test_strip_legacy_suffix(self):
        """Test legacy suffix removal."""
        assert strip_legacy_suffix('/services/event-planning-old/') == '/services/event-planning'
        assert strip_legacy_suffix('/page-2/') == '/page'
        assert strip_legacy_suffix('/normal-page/') == '/normal-page'


class TestPageClassification(TestCase):
    """Test page type classification (priority-ordered rules)."""
    
    def test_homepage(self):
        """Test homepage classification."""
        assert _classify_page_type('/', [], 0, '', None, True) == 'homepage'
        assert _classify_page_type('/', [], 0, '', None, False) == 'homepage'
    
    def test_location_pages(self):
        """Test location page classification."""
        path = '/service-area/event-planner/brooklyn/'
        parts = ['service-area', 'event-planner', 'brooklyn']
        assert _classify_page_type(path, parts, 3, 'service-area', None, False) == 'location'
        
        path = '/locations/manhattan/'
        parts = ['locations', 'manhattan']
        assert _classify_page_type(path, parts, 2, 'locations', None, False) == 'location'
    
    def test_blog_posts(self):
        """Test blog post classification."""
        # Date pattern
        path = '/2024/02/post-title/'
        parts = ['2024', '02', 'post-title']
        assert _classify_page_type(path, parts, 3, '2024', None, False) == 'blog'
        
        # Blog folder
        path = '/blog/article-title/'
        parts = ['blog', 'article-title']
        assert _classify_page_type(path, parts, 2, 'blog', None, False) == 'blog'
    
    def test_woocommerce_product(self):
        """Test WooCommerce product classification."""
        path = '/product/jazz-shoes/'
        parts = ['product', 'jazz-shoes']
        assert _classify_page_type(path, parts, 2, 'product', 'product', False) == 'product'
    
    def test_woocommerce_category(self):
        """Test WooCommerce category classification."""
        path = '/product-category/dance/'
        parts = ['product-category', 'dance']
        assert _classify_page_type(path, parts, 2, 'product-category', 'product_cat', False) == 'category_woo'
    
    def test_shop_hierarchy(self):
        """Test /shop/ hierarchy classification."""
        # Shop root (depth 1)
        path = '/shop/'
        parts = ['shop']
        assert _classify_page_type(path, parts, 1, 'shop', None, False) == 'shop_root'
        
        # Shop category (depth 2)
        path = '/shop/dance/'
        parts = ['shop', 'dance']
        assert _classify_page_type(path, parts, 2, 'shop', None, False) == 'category_shop'
        
        # Shop product (depth 3+)
        path = '/shop/dance/jazz-shoes/'
        parts = ['shop', 'dance', 'jazz-shoes']
        assert _classify_page_type(path, parts, 3, 'shop', None, False) == 'product'
    
    def test_product_category_depth(self):
        """Test /product-category/ depth rules (v2.1 fix)."""
        # Depth 2 = category
        path = '/product-category/dance/'
        parts = ['product-category', 'dance']
        assert _classify_page_type(path, parts, 2, 'product-category', None, False) == 'category_woo'
        
        # Depth 3+ = subcategory (NOT product) - this is the v2.1 fix
        path = '/product-category/dance/jazz/'
        parts = ['product-category', 'dance', 'jazz']
        assert _classify_page_type(path, parts, 3, 'product-category', None, False) == 'product'
    
    def test_service_pages(self):
        """Test service page classification."""
        # Service hub (depth 1)
        path = '/services/'
        parts = ['services']
        assert _classify_page_type(path, parts, 1, 'services', None, False) == 'service_hub'
        
        # Service spoke (depth 2+)
        path = '/services/event-planning/'
        parts = ['services', 'event-planning']
        assert _classify_page_type(path, parts, 2, 'services', None, False) == 'service_spoke'
    
    def test_portfolio(self):
        """Test portfolio classification."""
        path = '/portfolio/wedding-event/'
        parts = ['portfolio', 'wedding-event']
        assert _classify_page_type(path, parts, 2, 'portfolio', None, False) == 'portfolio'
    
    def test_utility_pages(self):
        """Test utility page classification."""
        path = '/cart/'
        parts = ['cart']
        assert _classify_page_type(path, parts, 1, 'cart', None, False) == 'utility'
        
        path = '/my-account/orders/'
        parts = ['my-account', 'orders']
        assert _classify_page_type(path, parts, 2, 'my-account', None, False) == 'utility'
    
    def test_uncategorized_fallback(self):
        """Test fallback to uncategorized."""
        path = '/random-page/'
        parts = ['random-page']
        assert _classify_page_type(path, parts, 1, 'random-page', None, False) == 'uncategorized'


class TestLegacyFlagNotType(TestCase):
    """Test that legacy detection is a BOOLEAN FLAG, not a page type."""
    
    def test_legacy_is_boolean_flag(self):
        """Legacy suffix doesn't override page classification."""
        # A blog post with -old suffix is still a BLOG, with is_legacy_variant=True
        assert is_legacy_variant('/blog/post-old/') == True
        
        # Classification should return 'blog', not 'legacy'
        path = '/blog/post-old/'
        parts = ['blog', 'post-old']
        assert _classify_page_type(path, parts, 2, 'blog', None, False) == 'blog'
        
        # The calling code (phase1_ingest.py) sets is_legacy_variant separately
