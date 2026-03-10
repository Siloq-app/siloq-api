"""
Test Group F: Phase 5 Wrong Winner Detection

Tests intent mismatch, page type mismatch, geographic mismatch, homepage hoarding.
"""
import pytest
from django.test import TestCase
from seo.cannibalization.utils import classify_query_intent, is_plural_query


class TestIntentClassification(TestCase):
    """Test query intent classification."""
    
    def test_transactional_intent(self):
        """Queries with buy/hire/service keywords = transactional."""
        queries = [
            'hire event planner',
            'event planning service near me',
            'book event planner brooklyn',
            'event planning company',
        ]
        
        for query in queries:
            intent, has_local = classify_query_intent(query)
            assert intent == 'transactional', f"Query '{query}' should be transactional"
    
    def test_informational_intent(self):
        """Queries with how/what/guide keywords = informational."""
        queries = [
            'how to plan an event',
            'what is event planning',
            'event planning guide',
            'event planning tips',
        ]
        
        for query in queries:
            intent, has_local = classify_query_intent(query)
            assert intent == 'informational', f"Query '{query}' should be informational"
    
    def test_listicle_intent(self):
        """Queries with best/top/review = listicle."""
        queries = [
            'best event planners in brooklyn',
            'top event planning companies',
            'event planning services review',
        ]
        
        for query in queries:
            intent, has_local = classify_query_intent(query)
            assert intent == 'listicle', f"Query '{query}' should be listicle"
    
    def test_local_modifier_detection(self):
        """Detect local modifiers (near me, in, etc.)."""
        queries_with_local = [
            'event planner near me',
            'event planning in brooklyn',
            'local event planners',
        ]
        
        for query in queries_with_local:
            intent, has_local = classify_query_intent(query)
            assert has_local == True, f"Query '{query}' should have local modifier"
        
        queries_without_local = [
            'event planning tips',
            'how to plan events',
        ]
        
        for query in queries_without_local:
            intent, has_local = classify_query_intent(query)
            assert has_local == False, f"Query '{query}' should not have local modifier"


class TestPluralDetection(TestCase):
    """Test plural query detection (category intent vs product intent)."""
    
    def test_plural_queries(self):
        """Plural queries = category intent."""
        queries = [
            'dance shoes',
            'event planners',
            'wedding venues',
        ]
        
        for query in queries:
            assert is_plural_query(query) == True, f"Query '{query}' should be plural"
    
    def test_singular_queries(self):
        """Singular queries = product intent."""
        queries = [
            'dance shoe',
            'event planner',
            'jazz shoe model x',
        ]
        
        for query in queries:
            assert is_plural_query(query) == False, f"Query '{query}' should be singular"
    
    def test_edge_cases(self):
        """Test edge cases (ss, us endings)."""
        # These should NOT be considered plural
        queries = [
            'glass',
            'boss',
            'canvas',
        ]
        
        for query in queries:
            assert is_plural_query(query) == False, f"Query '{query}' should not be plural"


class TestWrongWinnerScenarios(TestCase):
    """Test wrong winner detection logic (integration with Phase 5)."""
    
    def test_blog_for_transactional(self):
        """Blog ranking for transactional query = INTENT_MISMATCH."""
        # This would be tested in the full phase5_wrong_winner.run_phase5()
        # Here we just validate the intent classification supports it
        
        query = 'hire event planner brooklyn'
        intent, has_local = classify_query_intent(query)
        
        assert intent == 'transactional'
        # If winner_type == 'blog', this should trigger INTENT_MISMATCH
    
    def test_product_for_plural(self):
        """Product ranking for plural query = PAGE_TYPE_MISMATCH."""
        query = 'dance shoes'
        
        assert is_plural_query(query) == True
        # If winner_type == 'product', this should trigger PAGE_TYPE_MISMATCH
    
    def test_homepage_for_specific_query(self):
        """Homepage ranking for specific service = HOMEPAGE_HOARDING."""
        query = 'event planning services'
        intent, has_local = classify_query_intent(query)
        
        assert intent == 'transactional'
        # If winner_type == 'homepage', this should trigger HOMEPAGE_HOARDING
