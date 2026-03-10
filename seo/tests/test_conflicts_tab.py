"""
Deep test cases for Conflicts tab endpoints (Section 11.3).
Tests real GSC data integration, conflict detection, and approval queue workflow.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
User = get_user_model()
from rest_framework.test import APIClient
from rest_framework import status
from uuid import uuid4
from datetime import datetime, timedelta
from django.utils import timezone

from sites.models import Site
from seo.models import Page, SEOData, Conflict, ContentJob, GSCData


class ConflictsTabDeepTestCase(TestCase):
    """Test conflicts tab endpoints with real data integration."""
    
    def setUp(self):
        """Set up comprehensive test data."""
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
        
        # Create test pages with SEO data
        self.page1 = Page.objects.create(
            site=self.site,
            wp_post_id=1,
            url='https://example.com/seo-services',
            title='SEO Services - Our Company',
            is_money_page=True
        )
        
        self.page2 = Page.objects.create(
            site=self.site,
            wp_post_id=2,
            url='https://example.com/blog/best-seo-services',
            title='Best SEO Services - Blog Post',
            is_money_page=False
        )
        
        self.page3 = Page.objects.create(
            site=self.site,
            wp_post_id=3,
            url='https://example.com/local-seo',
            title='Local SEO Services',
            is_money_page=True
        )
        
        # Create SEO data
        SEOData.objects.create(
            page=self.page1,
            seo_score=85,
            word_count=1200
        )
        
        SEOData.objects.create(
            page=self.page2,
            seo_score=65,
            word_count=800
        )
        
        SEOData.objects.create(
            page=self.page3,
            seo_score=75,
            word_count=900
        )
        
        # Create GSC data for conflicts
        self.gsc_data_1 = GSCData.objects.create(
            page=self.page1,
            site=self.site,
            query='best seo services 2024',
            impressions=1250,
            clicks=45,
            position=3.2,
            ctr=3.6,
            date_start=timezone.now().date() - timedelta(days=28),
            date_end=timezone.now().date()
        )
        
        self.gsc_data_2 = GSCData.objects.create(
            page=self.page2,
            site=self.site,
            query='best seo services 2024',
            impressions=680,
            clicks=24,
            position=8.7,
            ctr=3.5,
            date_start=timezone.now().date() - timedelta(days=28),
            date_end=timezone.now().date()
        )
        
        self.gsc_data_3 = GSCData.objects.create(
            page=self.page3,
            site=self.site,
            query='local seo optimization',
            impressions=890,
            clicks=32,
            position=4.5,
            ctr=3.6,
            date_start=timezone.now().date() - timedelta(days=28),
            date_end=timezone.now().date()
        )
        
        # Create test conflicts
        self.conflict = Conflict.objects.create(
            site=self.site,
            page1=self.page1,
            page2=self.page2,
            query_string='best seo services 2024',
            winner_page=self.page1,
            recommendation='Merge blog content into main service page and 301 redirect blog URL',
            severity_score=85,
            location_differentiation=[
                {
                    'location': 'New York',
                    'page1_position': 2.1,
                    'page2_position': 15.3,
                    'recommendation': 'Page 1 dominates in New York market, consolidate content'
                }
            ]
        )
        
        self.dismissed_conflict = Conflict.objects.create(
            site=self.site,
            page1=self.page1,
            page2=self.page3,
            query_string='seo audit tools',
            winner_page=self.page1,
            recommendation='Combine tool page with comparison blog for comprehensive resource',
            severity_score=45,
            is_dismissed=True
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
        self.assertIn('severity_filter', data)
        self.assertIn('site_info', data)
        self.assertEqual(data['show_dismissed'], False)
        self.assertEqual(data['severity_filter'], 'all')
        
        # Should return only active conflicts (not dismissed)
        conflicts = data['conflicts']
        self.assertEqual(len(conflicts), 1)
        
        # Verify conflict structure
        conflict = conflicts[0]
        self.assertIn('query_string', conflict)  # GSC query string for card header
        self.assertIn('page1', conflict)
        self.assertIn('page2', conflict)
        self.assertIn('location_differentiation', conflict)
        self.assertIn('recommendation', conflict)
        self.assertIn('is_dismissed', conflict)
        self.assertIn('severity_score', conflict)
        self.assertIn('status', conflict)
        
        # Verify GSC query string is used as header (not title_keyword_overlap)
        self.assertEqual(conflict['query_string'], 'best seo services 2024')
        
        # Verify page card structure with real GSC data
        page1 = conflict['page1']
        self.assertEqual(page1['title'], 'SEO Services - Our Company')
        self.assertEqual(page1['impressions'], 1250)  # Real GSC data
        self.assertEqual(page1['position'], 3.2)
        self.assertEqual(page1['clicks'], 45)
        self.assertEqual(page1['click_share'], 65.2)  # Calculated percentage
        self.assertTrue(page1['is_winner'])
        self.assertEqual(page1['seo_score'], 85)
        
        page2 = conflict['page2']
        self.assertEqual(page2['title'], 'Best SEO Services - Blog Post')
        self.assertEqual(page2['impressions'], 680)
        self.assertEqual(page2['position'], 8.7)
        self.assertEqual(page2['clicks'], 24)
        self.assertEqual(page2['click_share'], 34.8)
        self.assertFalse(page2['is_winner'])
        self.assertEqual(page2['seo_score'], 65)
    
    def test_conflicts_list_show_dismissed(self):
        """Test conflicts list endpoint with dismissed conflicts shown."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/?show_dismissed=true'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertEqual(data['show_dismissed'], True)
        # Should include dismissed conflicts
        conflicts = data['conflicts']
        self.assertEqual(len(conflicts), 2)
        
        dismissed_conflicts = [c for c in conflicts if c['is_dismissed']]
        self.assertEqual(len(dismissed_conflicts), 1)
    
    def test_conflicts_list_severity_filter(self):
        """Test conflicts list endpoint with severity filtering."""
        # Test high severity filter
        url = f'/api/v1/sites/{self.site.id}/conflicts/?severity=high'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        conflicts = data['conflicts']
        for conflict in conflicts:
            self.assertGreaterEqual(conflict['severity_score'], 80)
        
        # Test low severity filter
        url = f'/api/v1/sites/{self.site.id}/conflicts/?severity=low'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        conflicts = data['conflicts']
        for conflict in conflicts:
            self.assertLess(conflict['severity_score'], 50)
    
    def test_accept_recommendation(self):
        """Test accept recommendation endpoint with approval queue integration."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/{self.conflict.id}/accept/'
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('message', data)
        self.assertIn('content_job_id', data)
        self.assertIn('conflict_id', data)
        self.assertIn('status', data)
        self.assertIn('priority', data)
        self.assertIn('estimated_processing_time', data)
        
        self.assertEqual(data['message'], 'Recommendation sent to Approvals queue')
        self.assertEqual(data['status'], 'pending_approval')
        self.assertEqual(data['priority'], 'high')  # Based on severity score >= 80
        
        # Verify content job was created
        content_job = ContentJob.objects.get(id=data['content_job_id'])
        self.assertEqual(content_job.job_type, 'conflict_resolution')
        self.assertEqual(content_job.status, 'pending_approval')
        self.assertEqual(content_job.conflict, self.conflict)
        self.assertEqual(content_job.target_page, self.conflict.winner_page)
        self.assertEqual(content_job.created_by, self.user)
        
        # Verify conflict status was updated
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, 'in_approval_queue')
    
    def test_dismiss_conflict(self):
        """Test dismiss conflict endpoint."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/{self.conflict.id}/dismiss/'
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('message', data)
        self.assertIn('conflict_id', data)
        self.assertIn('is_dismissed', data)
        
        self.assertEqual(data['message'], 'Conflict dismissed')
        self.assertTrue(data['is_dismissed'])
        
        # Verify conflict was dismissed
        self.conflict.refresh_from_db()
        self.assertTrue(self.conflict.is_dismissed)
    
    def test_resolve_conflict(self):
        """Test resolve conflict endpoint."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/{self.conflict.id}/resolve/'
        response = self.client.post(url, {'notes': 'Resolved by merging content'}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('message', data)
        self.assertIn('conflict_id', data)
        self.assertIn('status', data)
        self.assertIn('resolved_at', data)
        
        self.assertEqual(data['message'], 'Conflict marked as resolved')
        self.assertEqual(data['status'], 'resolved')
        
        # Verify conflict was resolved
        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, 'resolved')
        self.assertIsNotNone(self.conflict.resolved_at)
    
    def test_conflict_detection_integration(self):
        """Test conflict detection algorithm integration."""
        # Create additional GSC data that should trigger conflict detection
        GSCData.objects.create(
            page=self.page3,
            site=self.site,
            query='best seo services 2024',  # Same query as page1 and page2
            impressions=340,
            clicks=12,
            position=12.1,
            ctr=3.5,
            date_start=timezone.now().date() - timedelta(days=28),
            date_end=timezone.now().date()
        )
        
        # Delete existing conflicts to trigger detection
        Conflict.objects.all().delete()
        
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Should detect and create conflicts automatically
        conflicts = data['conflicts']
        self.assertGreater(len(conflicts), 0)
        
        # Verify detected conflicts have proper structure
        for conflict in conflicts:
            self.assertIn('query_string', conflict)
            self.assertIn('page1', conflict)
            self.assertIn('page2', conflict)
            self.assertIn('severity_score', conflict)
            self.assertIsInstance(conflict['severity_score'], (int, float))
            self.assertGreaterEqual(conflict['severity_score'], 0)
            self.assertLessEqual(conflict['severity_score'], 100)
    
    def test_location_differentiation_structure(self):
        """Test location differentiation data structure."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        conflicts = data['conflicts']
        if conflicts:
            conflict = conflicts[0]
            location_diff = conflict['location_differentiation']
            
            self.assertIsInstance(location_diff, list)
            
            if location_diff:  # May be empty for some conflicts
                location = location_diff[0]
                self.assertIn('location', location)
                self.assertIn('page1_position', location)
                self.assertIn('page2_position', location)
                self.assertIn('recommendation', location)
                
                # Verify position data types
                self.assertIsInstance(location['page1_position'], (int, float))
                self.assertIsInstance(location['page2_position'], (int, float))
    
    def test_ai_recommendation_generation(self):
        """Test AI recommendation generation for different scenarios."""
        # Test with clear winner (page1 dominates)
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        conflicts = data['conflicts']
        if conflicts:
            conflict = conflicts[0]
            recommendation = conflict['recommendation']
            
            self.assertIsInstance(recommendation, str)
            self.assertGreater(len(recommendation), 10)  # Should be meaningful recommendation
            
            # Should contain actionable advice
            action_words = ['merge', 'redirect', 'consolidate', 'optimize', 'differentiate']
            has_action = any(word in recommendation.lower() for word in action_words)
            self.assertTrue(has_action, f"Recommendation should contain actionable advice: {recommendation}")
    
    def test_click_share_calculation(self):
        """Test click share percentage calculation."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        conflicts = data['conflicts']
        if conflicts:
            conflict = conflicts[0]
            page1_click_share = conflict['page1']['click_share']
            page2_click_share = conflict['page2']['click_share']
            
            # Click shares should sum to 100%
            self.assertAlmostEqual(page1_click_share + page2_click_share, 100.0, places=1)
            
            # Each click share should be between 0 and 100
            self.assertGreaterEqual(page1_click_share, 0)
            self.assertLessEqual(page1_click_share, 100)
            self.assertGreaterEqual(page2_click_share, 0)
            self.assertLessEqual(page2_click_share, 100)
    
    def test_site_info_in_response(self):
        """Test site information is included in response."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        site_info = data['site_info']
        self.assertEqual(site_info['id'], self.site.id)
        self.assertEqual(site_info['name'], self.site.name)
        self.assertEqual(site_info['url'], self.site.url)
    
    def test_winner_determination_logic(self):
        """Test winner determination based on GSC metrics."""
        url = f'/api/v1/sites/{self.site.id}/conflicts/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        conflicts = data['conflicts']
        if conflicts:
            conflict = conflicts[0]
            
            # Only one page should be marked as winner
            page1_winner = conflict['page1']['is_winner']
            page2_winner = conflict['page2']['is_winner']
            
            self.assertTrue(page1_winner != page2_winner, "Exactly one page should be marked as winner")
            
            # Winner should have better performance metrics
            if page1_winner:
                self.assertGreaterEqual(conflict['page1']['impressions'], conflict['page2']['impressions'])
                self.assertLessEqual(conflict['page1']['position'], conflict['page2']['position'])
            else:
                self.assertGreaterEqual(conflict['page2']['impressions'], conflict['page1']['impressions'])
                self.assertLessEqual(conflict['page2']['position'], conflict['page1']['position'])
