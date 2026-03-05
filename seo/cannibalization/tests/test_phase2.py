"""
Test Group B: Phase 2 Safe Filters

Tests product sibling, parent-child, and geographic variant detection.
"""
import pytest
from django.test import TestCase
from unittest.mock import Mock
from seo.cannibalization.phase2_safe_filters import (
    _are_product_siblings,
    _are_parent_child,
    _are_geographic_variants,
)


def mock_page_class(page_id, url, classified_type, parent_path='', slug_last='', 
                    is_legacy=False, geo_node=''):
    """Helper to create mock PageClassification."""
    mock = Mock()
    mock.page_id = page_id
    mock.url = url
    mock.normalized_path = url  # Simplified for tests
    mock.classified_type = classified_type
    mock.parent_path = parent_path
    mock.slug_last = slug_last
    mock.is_legacy_variant = is_legacy
    mock.geo_node = geo_node
    return mock


class TestProductSiblings(TestCase):
    """Test product sibling filter."""
    
    def test_valid_product_siblings(self):
        """Two products in same category = SAFE."""
        page_a = mock_page_class(1, '/shop/dance/jazz-shoes/', 'product', '/shop/dance', 'jazz-shoes')
        page_b = mock_page_class(2, '/shop/dance/tap-shoes/', 'product', '/shop/dance', 'tap-shoes')
        
        assert _are_product_siblings(page_a, page_b) == True
    
    def test_different_categories(self):
        """Products in different categories = NOT siblings."""
        page_a = mock_page_class(1, '/shop/dance/jazz-shoes/', 'product', '/shop/dance', 'jazz-shoes')
        page_b = mock_page_class(2, '/shop/apparel/shirts/', 'product', '/shop/apparel', 'shirts')
        
        assert _are_product_siblings(page_a, page_b) == False
    
    def test_same_slug(self):
        """Products with identical slug = NOT siblings (duplicates)."""
        page_a = mock_page_class(1, '/shop/dance/jazz-shoes/', 'product', '/shop/dance', 'jazz-shoes')
        page_b = mock_page_class(2, '/shop/dance/jazz-shoes/', 'product', '/shop/dance', 'jazz-shoes')
        
        assert _are_product_siblings(page_a, page_b) == False
    
    def test_legacy_variant(self):
        """Product and its legacy variant = NOT siblings."""
        page_a = mock_page_class(1, '/shop/dance/jazz-shoes/', 'product', '/shop/dance', 'jazz-shoes')
        page_b = mock_page_class(2, '/shop/dance/jazz-shoes-old/', 'product', '/shop/dance', 'jazz-shoes-old', is_legacy=True)
        
        assert _are_product_siblings(page_a, page_b) == False
    
    def test_not_both_products(self):
        """Product + category = NOT siblings."""
        page_a = mock_page_class(1, '/shop/dance/', 'category_shop', '/shop', 'dance')
        page_b = mock_page_class(2, '/shop/dance/jazz-shoes/', 'product', '/shop/dance', 'jazz-shoes')
        
        assert _are_product_siblings(page_a, page_b) == False


class TestParentChild(TestCase):
    """Test parent-child relationship filter."""
    
    def test_direct_parent_child(self):
        """Hub page and direct child spoke = SAFE."""
        page_a = mock_page_class(1, '/services/', 'service_hub')
        page_b = mock_page_class(2, '/services/event-planning/', 'service_spoke')
        
        assert _are_parent_child(page_a, page_b) == True
    
    def test_grandparent_not_parent(self):
        """Grandparent relationship = NOT safe (not direct)."""
        page_a = mock_page_class(1, '/services/', 'service_hub')
        page_b = mock_page_class(2, '/services/event-planning/weddings/', 'service_spoke')
        
        assert _are_parent_child(page_a, page_b) == False
    
    def test_child_with_modifier_not_distinct(self):
        """Child slug that's just parent + modifier = NOT safe."""
        page_a = mock_page_class(1, '/services/event-planning/', 'service_spoke')
        page_b = mock_page_class(2, '/services/event-planning/event-planning-services/', 'service_spoke')
        
        # This should NOT be considered parent-child because child slug contains all parent tokens
        assert _are_parent_child(page_a, page_b) == False


class TestGeographicVariants(TestCase):
    """Test geographic variant filter."""
    
    def test_different_cities(self):
        """Same service in different cities = SAFE."""
        page_a = mock_page_class(1, '/service-area/event-planner/brooklyn/', 'location', geo_node='brooklyn')
        page_b = mock_page_class(2, '/service-area/event-planner/manhattan/', 'location', geo_node='manhattan')
        
        assert _are_geographic_variants(page_a, page_b) == True
    
    def test_same_city(self):
        """Same service, same city = NOT safe (duplicate)."""
        page_a = mock_page_class(1, '/service-area/event-planner/brooklyn/', 'location', geo_node='brooklyn')
        page_b = mock_page_class(2, '/locations/event-planner/brooklyn/', 'location', geo_node='brooklyn')
        
        assert _are_geographic_variants(page_a, page_b) == False
    
    def test_not_both_location(self):
        """Location + service = NOT geographic variants."""
        page_a = mock_page_class(1, '/service-area/brooklyn/', 'location', geo_node='brooklyn')
        page_b = mock_page_class(2, '/services/event-planning/', 'service_spoke')
        
        assert _are_geographic_variants(page_a, page_b) == False
    
    def test_normalized_geo_comparison(self):
        """Brooklyn vs brooklyn (case/dash variance) = same city."""
        page_a = mock_page_class(1, '/locations/Brooklyn/', 'location', geo_node='Brooklyn')
        page_b = mock_page_class(2, '/service-area/new-york/brooklyn/', 'location', geo_node='brooklyn')
        
        # Both normalize to 'brooklyn'
        from seo.cannibalization.utils import normalize_geo
        assert normalize_geo('Brooklyn') == normalize_geo('brooklyn')
        
        assert _are_geographic_variants(page_a, page_b) == False
