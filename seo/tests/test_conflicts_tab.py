"""
Test cases for Conflicts tab endpoints (Section 11.3).
"""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from uuid import uuid4

from sites.models import Site
from seo.models import Page, SEOData


class ConflictsTabTestCase(TestCase):
    """Test conflicts tab endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        
        self.site = Site.objects.create(
            user=self.user,
            name='Test Site',
            url='https://example.com'
        )
        
        # Create test pages
        self.page1 = Page.objects.create(
            site=self.site,
            wp_post_id=1,
            url='https://example.com/page1',
            title='Test Page 1',
            is_money_page=True
        )
        
        self.page2 = Page.objects.create(
            site=self.site,
            wp_post_id=2,
            url='https://example.com/page2',
            title='Test Page 2',
            is_money_page=False
        )
        
        # Create SEO data
        SEOData.objects.create(
            page=self.page1,
            seo_score=85
        )
        
        SEOData.objects.create(
            page=self.page2,
            seo_score=45
        )
    
    def test_conflicts_list_default_view(self):
        """Test conflicts list endpoint with default view (no dismissed conflicts)."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('conflicts', data)
        self.assertIn('total_count', data)
        self.assertIn('show_dismissed', data)
        self.assertEqual(data['show_dismissed'], False)
        
        # Should return mock conflicts (not dismissed)
        conflicts = data['conflicts']
        self.assertGreater(len(conflicts), 0)
        
        # Verify conflict structure
        conflict = conflicts[0]
        self.assertIn('query_string', conflict)  # GSC query string for card header
        self.assertIn('page1', conflict)
        self.assertIn('page2', conflict)
        self.assertIn('location_differentiation', conflict)
        self.assertIn('recommendation', conflict)
        self.assertIn('is_dismissed', conflict)
        
        # Verify page card structure
        page1 = conflict['page1']
        self.assertIn('title', page1)
        self.assertIn('url', page1)
        self.assertIn('impressions', page1)
        self.assertIn('position', page1)
        self.assertIn('clicks', page1)
        self.assertIn('click_share', page1)
        self.assertIn('is_winner', page1)
    
    def test_conflicts_list_show_dismissed(self):
        """Test conflicts list endpoint with dismissed conflicts shown."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/?show_dismissed=true'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertEqual(data['show_dismissed'], True)
        # Should include dismissed conflicts
        conflicts = data['conflicts']
        dismissed_conflicts = [c for c in conflicts if c['is_dismissed']]
        self.assertGreater(len(dismissed_conflicts), 0)
    
    def test_accept_recommendation(self):
        """Test accept recommendation endpoint."""
        conflict_id = str(uuid4())
        url = f'/api/v1/sites/{self.site.id}/conflicts/{conflict_id}/accept/'
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('message', data)
        self.assertIn('content_job_id', data)
        self.assertIn('conflict_id', data)
        self.assertIn('status', data)
        self.assertEqual(data['status'], 'pending_approval')
        self.assertEqual(data['message'], 'Recommendation sent to Approvals queue')
    
    def test_conflicts_response_format(self):
        """Test that conflicts response matches expected format for frontend."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        conflicts = data['conflicts']
        if conflicts:
            conflict = conflicts[0]
            
            # Verify GSC query string is in card header format
            self.assertIsInstance(conflict['query_string'], str)
            self.assertGreater(len(conflict['query_string']), 0)
            
            # Verify page cards have required metrics
            for page_key in ['page1', 'page2']:
                page = conflict[page_key]
                self.assertIsInstance(page['impressions'], int)
                self.assertIsInstance(page['position'], (int, float))
                self.assertIsInstance(page['clicks'], int)
                self.assertIsInstance(page['click_share'], (int, float))
                self.assertIsInstance(page['is_winner'], bool)
            
            # Verify location differentiation is present but may be empty
            self.assertIsInstance(conflict['location_differentiation'], list)
            
            # Verify recommendation exists
            self.assertIsInstance(conflict['recommendation'], str)
