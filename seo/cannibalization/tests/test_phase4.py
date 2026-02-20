"""
Test Group E: Phase 4 GSC Validation

Tests GSC impression share calculation and conflict confirmation.
"""
import pytest
from django.test import TestCase
from unittest.mock import Mock
from seo.cannibalization.phase4_gsc_validate import _analyze_query_group, _calculate_severity


class TestImpressionShareCalculation(TestCase):
    """Test impression share and threshold logic."""
    
    def test_primary_share_above_threshold(self):
        """Primary share >= 85% = NOT cannibalization."""
        rows = [
            {
                'query': 'event planning',
                'page_url': 'https://example.com/services/event-planning/',
                'page_class': Mock(classified_type='service_spoke', normalized_url='example.com/services/event-planning'),
                'clicks': 50,
                'impressions': 900,
                'position': 3.2,
            },
            {
                'query': 'event planning',
                'page_url': 'https://example.com/blog/event-planning-tips/',
                'page_class': Mock(classified_type='blog', normalized_url='example.com/blog/event-planning-tips'),
                'clicks': 5,
                'impressions': 100,
                'position': 12.5,
            }
        ]
        
        issue = _analyze_query_group('event planning', rows)
        
        # Should return None (not cannibalization)
        assert issue is None
    
    def test_secondary_share_above_threshold(self):
        """Secondary share >= 15% = CONFIRMED cannibalization."""
        rows = [
            {
                'query': 'event planning brooklyn',
                'page_url': 'https://example.com/service-area/brooklyn/',
                'page_class': Mock(classified_type='location', normalized_url='example.com/service-area/brooklyn'),
                'clicks': 30,
                'impressions': 600,
                'position': 4.1,
            },
            {
                'query': 'event planning brooklyn',
                'page_url': 'https://example.com/services/event-planning/',
                'page_class': Mock(classified_type='service_spoke', normalized_url='example.com/services/event-planning'),
                'clicks': 15,
                'impressions': 400,
                'position': 8.3,
            }
        ]
        
        issue = _analyze_query_group('event planning brooklyn', rows)
        
        assert issue is not None
        assert issue['conflict_type'] == 'GSC_CONFIRMED'
        assert issue['severity'] in ['MEDIUM', 'HIGH']
    
    def test_noise_filtering(self):
        """Pages with <5% share AND 0 clicks are filtered."""
        rows = [
            {
                'query': 'dance shoes',
                'page_url': 'https://example.com/shop/dance/',
                'page_class': Mock(classified_type='category_shop', normalized_url='example.com/shop/dance'),
                'clicks': 80,
                'impressions': 800,
                'position': 2.5,
            },
            {
                'query': 'dance shoes',
                'page_url': 'https://example.com/product/jazz-shoe/',
                'page_class': Mock(classified_type='product', normalized_url='example.com/product/jazz-shoe'),
                'clicks': 20,
                'impressions': 150,
                'position': 6.2,
            },
            {
                'query': 'dance shoes',
                'page_url': 'https://example.com/blog/best-dance-shoes/',
                'page_class': Mock(classified_type='blog', normalized_url='example.com/blog/best-dance-shoes'),
                'clicks': 0,
                'impressions': 30,  # <5% of total, 0 clicks
                'position': 18.7,
            }
        ]
        
        issue = _analyze_query_group('dance shoes', rows)
        
        # Blog should be filtered out, only 2 pages in conflict
        if issue:
            assert len(issue['pages']) == 2


class TestSeverityCalculation(TestCase):
    """Test severity scoring logic."""
    
    def test_severe_multiple_pages_10_percent(self):
        """3+ pages each with 10%+ share = SEVERE."""
        rows = [
            {'share': 0.40},
            {'share': 0.30},
            {'share': 0.20},
            {'share': 0.10},
        ]
        
        severity = _calculate_severity(rows)
        assert severity == 'SEVERE'
    
    def test_high_secondary_35_percent(self):
        """Secondary page 35%+ share = HIGH."""
        rows = [
            {'share': 0.60},
            {'share': 0.40},
        ]
        
        severity = _calculate_severity(rows)
        assert severity == 'HIGH'
    
    def test_medium_secondary_15_percent(self):
        """Secondary page 15-35% share = MEDIUM."""
        rows = [
            {'share': 0.75},
            {'share': 0.25},
        ]
        
        severity = _calculate_severity(rows)
        assert severity == 'MEDIUM'
    
    def test_low_minor_split(self):
        """Small impression split = LOW."""
        rows = [
            {'share': 0.90},
            {'share': 0.10},
        ]
        
        severity = _calculate_severity(rows)
        assert severity == 'LOW'
