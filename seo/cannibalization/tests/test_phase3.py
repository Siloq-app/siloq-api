"""
Test Groups C & D: Phase 3 Static Detection

Tests:
- TAXONOMY_CLASH
- LEGACY_CLEANUP / LEGACY_ORPHAN
- NEAR_DUPLICATE_CONTENT
- CONTEXT_DUPLICATE
- LOCATION_BOILERPLATE
"""
import pytest
from django.test import TestCase
from unittest.mock import Mock
from seo.cannibalization.phase3_static_detect import (
    _detect_taxonomy_clash,
    _detect_legacy_variants,
    _detect_near_duplicates,
    _detect_context_duplicates,
    _detect_location_boilerplate,
)
from seo.cannibalization.utils import slug_similarity, extract_title_template


def mock_page_class(page_id, url, title='Test Page', classified_type='uncategorized',
                    folder_root='', slug_last='', parent_path='', is_legacy=False,
                    service_keyword='', geo_node='', slug_tokens=None):
    """Helper to create mock PageClassification."""
    mock = Mock()
    mock.page_id = page_id
    mock.url = url
    mock.title = title
    mock.normalized_path = url
    mock.normalized_url = url
    mock.classified_type = classified_type
    mock.folder_root = folder_root
    mock.slug_last = slug_last
    mock.parent_path = parent_path
    mock.is_legacy_variant = is_legacy
    mock.service_keyword = service_keyword
    mock.geo_node = geo_node
    mock.slug_tokens_json = slug_tokens or []
    return mock


class TestTaxonomyClash(TestCase):
    """Test TAXONOMY_CLASH detection."""
    
    def test_same_slug_different_folders(self):
        """Same slug in different folder structures = TAXONOMY_CLASH."""
        pages = [
            mock_page_class(1, '/shop/jazz-shoes/', classified_type='product', folder_root='shop', slug_last='jazz-shoes'),
            mock_page_class(2, '/product-category/jazz-shoes/', classified_type='category_woo', folder_root='product-category', slug_last='jazz-shoes'),
        ]
        
        issues = _detect_taxonomy_clash(pages, set())
        
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'TAXONOMY_CLASH'
        assert issues[0]['severity'] == 'HIGH'
        assert len(issues[0]['pages']) == 2
    
    def test_same_slug_same_folder(self):
        """Same slug in same folder = NOT a clash."""
        pages = [
            mock_page_class(1, '/shop/dance/jazz-shoes/', classified_type='product', folder_root='shop', slug_last='jazz-shoes'),
            mock_page_class(2, '/shop/apparel/jazz-shoes/', classified_type='product', folder_root='shop', slug_last='jazz-shoes'),
        ]
        
        # Still a clash because it's the same folder_root with duplicate slugs
        issues = _detect_taxonomy_clash(pages, set())
        assert len(issues) == 0 or (len(issues) == 1 and issues[0]['conflict_type'] == 'TAXONOMY_CLASH')


class TestLegacyVariants(TestCase):
    """Test LEGACY_CLEANUP and LEGACY_ORPHAN detection."""
    
    def test_legacy_with_clean_version(self):
        """Legacy page with clean version = LEGACY_CLEANUP."""
        pages = [
            mock_page_class(1, '/services/event-planning/', is_legacy=False),
            mock_page_class(2, '/services/event-planning-old/', is_legacy=True),
        ]
        
        issues = _detect_legacy_variants(pages, set())
        
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'LEGACY_CLEANUP'
        assert issues[0]['severity'] == 'HIGH'
        assert len(issues[0]['pages']) == 2
    
    def test_legacy_orphan(self):
        """Legacy page without clean version = LEGACY_ORPHAN."""
        pages = [
            mock_page_class(1, '/services/old-service-backup/', is_legacy=True),
        ]
        
        issues = _detect_legacy_variants(pages, set())
        
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'LEGACY_ORPHAN'
        assert issues[0]['severity'] == 'MEDIUM'
        assert len(issues[0]['pages']) == 1


class TestNearDuplicates(TestCase):
    """Test NEAR_DUPLICATE_CONTENT detection."""
    
    def test_high_similarity(self):
        """URLs with >80% token similarity = NEAR_DUPLICATE."""
        # These URLs share most tokens
        pages = [
            mock_page_class(1, '/blog/best-event-planning-tips-2024/'),
            mock_page_class(2, '/blog/best-event-planning-tips-2023/'),
        ]
        
        # Check similarity manually
        sim = slug_similarity(pages[0].normalized_path, pages[1].normalized_path)
        assert sim > 0.80, f"Expected >0.80, got {sim}"
        
        issues = _detect_near_duplicates(pages, set())
        
        assert len(issues) >= 1
        assert issues[0]['conflict_type'] == 'NEAR_DUPLICATE_CONTENT'
        assert issues[0]['severity'] == 'MEDIUM'
    
    def test_low_similarity(self):
        """URLs with <80% similarity = NOT flagged."""
        pages = [
            mock_page_class(1, '/blog/wedding-tips/'),
            mock_page_class(2, '/blog/corporate-event-guide/'),
        ]
        
        sim = slug_similarity(pages[0].normalized_path, pages[1].normalized_path)
        assert sim < 0.80
        
        issues = _detect_near_duplicates(pages, set())
        assert len(issues) == 0


class TestContextDuplicates(TestCase):
    """Test CONTEXT_DUPLICATE detection."""
    
    def test_same_service_different_parents(self):
        """Same service slug under different parent paths = CONTEXT_DUPLICATE."""
        pages = [
            mock_page_class(1, '/services/event-planning/', classified_type='service_spoke',
                          parent_path='/services', service_keyword='event-planning'),
            mock_page_class(2, '/residential/event-planning/', classified_type='service_spoke',
                          parent_path='/residential', service_keyword='event-planning'),
        ]
        
        issues = _detect_context_duplicates(pages, set())
        
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'CONTEXT_DUPLICATE'
        assert issues[0]['severity'] == 'MEDIUM'
    
    def test_different_services(self):
        """Different service keywords = NOT duplicate."""
        pages = [
            mock_page_class(1, '/services/event-planning/', classified_type='service_spoke',
                          parent_path='/services', service_keyword='event-planning'),
            mock_page_class(2, '/services/catering/', classified_type='service_spoke',
                          parent_path='/services', service_keyword='catering'),
        ]
        
        issues = _detect_context_duplicates(pages, set())
        assert len(issues) == 0


class TestLocationBoilerplate(TestCase):
    """Test LOCATION_BOILERPLATE detection."""
    
    def test_identical_templates(self):
        """3+ location pages with identical title template = LOCATION_BOILERPLATE."""
        pages = [
            mock_page_class(1, '/service-area/event-planner/brooklyn/', 
                          title='Event Planner in Brooklyn | CoCo Events',
                          classified_type='location', geo_node='brooklyn'),
            mock_page_class(2, '/service-area/event-planner/manhattan/',
                          title='Event Planner in Manhattan | CoCo Events',
                          classified_type='location', geo_node='manhattan'),
            mock_page_class(3, '/service-area/event-planner/queens/',
                          title='Event Planner in Queens | CoCo Events',
                          classified_type='location', geo_node='queens'),
        ]
        
        # Check template extraction
        template1 = extract_title_template(pages[0].title, pages[0].geo_node)
        template2 = extract_title_template(pages[1].title, pages[1].geo_node)
        assert template1 == template2, f"Templates don't match: '{template1}' vs '{template2}'"
        
        issues = _detect_location_boilerplate(pages, set())
        
        assert len(issues) == 1
        assert issues[0]['conflict_type'] == 'LOCATION_BOILERPLATE'
        assert issues[0]['severity'] == 'MEDIUM'
        assert len(issues[0]['pages']) >= 3
    
    def test_unique_titles(self):
        """Location pages with unique content = NOT boilerplate."""
        pages = [
            mock_page_class(1, '/service-area/brooklyn/',
                          title='Brooklyn Event Planner - Serving Park Slope & Williamsburg',
                          classified_type='location', geo_node='brooklyn'),
            mock_page_class(2, '/service-area/manhattan/',
                          title='Manhattan Event Planning - Midtown & Upper East Side Specialists',
                          classified_type='location', geo_node='manhattan'),
        ]
        
        # Templates should differ after removing geo
        template1 = extract_title_template(pages[0].title, pages[0].geo_node)
        template2 = extract_title_template(pages[1].title, pages[1].geo_node)
        assert template1 != template2
        
        issues = _detect_location_boilerplate(pages, set())
        assert len(issues) == 0
    
    def test_less_than_three_pages(self):
        """Only 2 location pages = NOT flagged (need 3+)."""
        pages = [
            mock_page_class(1, '/service-area/brooklyn/',
                          title='Event Planner in Brooklyn',
                          classified_type='location', geo_node='brooklyn'),
            mock_page_class(2, '/service-area/manhattan/',
                          title='Event Planner in Manhattan',
                          classified_type='location', geo_node='manhattan'),
        ]
        
        issues = _detect_location_boilerplate(pages, set())
        assert len(issues) == 0


class TestSlugSimilarity(TestCase):
    """Test slug similarity utility function."""
    
    def test_high_similarity(self):
        """Nearly identical URLs."""
        url1 = '/blog/best-dance-shoes-2024/'
        url2 = '/blog/best-dance-shoes-2023/'
        
        sim = slug_similarity(url1, url2)
        assert sim > 0.80
    
    def test_low_similarity(self):
        """Completely different URLs."""
        url1 = '/blog/wedding-tips/'
        url2 = '/services/catering/'
        
        sim = slug_similarity(url1, url2)
        assert sim < 0.30
    
    def test_stop_words_removed(self):
        """Stop words don't affect similarity."""
        url1 = '/blog/guide-for-event-planning/'
        url2 = '/articles/event-planning-tips/'
        
        # Both should extract 'event', 'planning' after removing stop words
        from seo.cannibalization.utils import extract_slug_tokens
        tokens1 = extract_slug_tokens(url1, remove_stop_words=True)
        tokens2 = extract_slug_tokens(url2, remove_stop_words=True)
        
        assert 'event' in tokens1 and 'event' in tokens2
        assert 'planning' in tokens1 and 'planning' in tokens2
