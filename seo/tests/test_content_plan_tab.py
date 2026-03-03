"""
Test cases for Content Plan tab endpoints (Section 11.5).
Tests content gaps analysis, topic suggestions, and pipeline management.
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
from seo.models import Page, SEOData, ContentJob


class ContentPlanTabTestCase(TestCase):
    """Test content plan tab endpoints with real data integration."""
    
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
        
        # Create money pages with varying supporting content
        self.money_page1 = Page.objects.create(
            site=self.site,
            wp_post_id=1,
            url='https://example.com/seo-services',
            title='SEO Services - Our Company',
            is_money_page=True
        )
        
        self.money_page2 = Page.objects.create(
            site=self.site,
            wp_post_id=2,
            url='https://example.com/ppc-advertising',
            title='PPC Advertising Services',
            is_money_page=True
        )
        
        self.money_page3 = Page.objects.create(
            site=self.site,
            wp_post_id=3,
            url='https://example.com/content-marketing',
            title='Content Marketing Strategy',
            is_money_page=True
        )
        
        # Create supporting pages
        self.supporting_page1 = Page.objects.create(
            site=self.site,
            wp_post_id=4,
            url='https://example.com/seo-tips',
            title='SEO Tips and Tricks',
            is_money_page=False
        )
        
        self.supporting_page2 = Page.objects.create(
            site=self.site,
            wp_post_id=5,
            url='https://example.com/ppc-guide',
            title='PPC Advertising Guide',
            is_money_page=False
        )
        
        # Create SEO data
        SEOData.objects.create(
            page=self.money_page1,
            seo_score=85,
            word_count=1200
        )
        
        SEOData.objects.create(
            page=self.money_page2,
            seo_score=65,
            word_count=800
        )
        
        SEOData.objects.create(
            page=self.money_page3,
            seo_score=75,
            word_count=900
        )
        
        SEOData.objects.create(
            page=self.supporting_page1,
            seo_score=70,
            word_count=600
        )
        
        SEOData.objects.create(
            page=self.supporting_page2,
            seo_score=80,
            word_count=1000
        )
        
        # Set up supporting content relationships
        self.money_page1.related_pages.add(self.supporting_page1)
        self.money_page2.related_pages.add(self.supporting_page2)
        # money_page3 has no supporting pages (content gap)
    
    def test_content_plan_default_gaps_view(self):
        """Test content plan endpoint with default gaps view."""
        url = f'/api/v1/sites/{self.site.id}/content-plan/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('content_plan', data)
        self.assertIn('view_type', data)
        self.assertIn('tab_badge_count', data)
        self.assertIn('total_money_pages', data)
        self.assertIn('pages_with_gaps', data)
        self.assertIn('min_supporting_threshold', data)
        self.assertIn('site_info', data)
        
        # Default view should be 'gaps'
        self.assertEqual(data['view_type'], 'gaps')
        
        # Should show pages with gaps (<2 supporting articles)
        content_plan = data['content_plan']
        self.assertGreater(len(content_plan), 0)
        
        # Should include money_page3 (no supporting content)
        page_ids = [page['id'] for page in content_plan]
        self.assertIn(str(self.money_page3.id), page_ids)
        
        # Tab badge count should match pages with gaps
        self.assertEqual(data['tab_badge_count'], data['pages_with_gaps'])
        self.assertGreater(data['tab_badge_count'], 0)
    
    def test_content_plan_all_view(self):
        """Test content plan endpoint with all money pages view."""
        url = f'/api/v1/sites/{self.site.id}/content-plan/?view=all'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Should show all money pages, not just those with gaps
        content_plan = data['content_plan']
        page_ids = [page['id'] for page in content_plan]
        
        self.assertIn(str(self.money_page1.id), page_ids)
        self.assertIn(str(self.money_page2.id), page_ids)
        self.assertIn(str(self.money_page3.id), page_ids)
        
        # Should have 3 total money pages
        self.assertEqual(data['total_money_pages'], 3)
    
    def test_content_plan_structure(self):
        """Test content plan response structure for frontend integration."""
        url = f'/api/v1/sites/{self.site.id}/content-plan/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        content_plan = data['content_plan']
        if content_plan:
            page = content_plan[0]
            
            # Verify required fields
            required_fields = [
                'id', 'title', 'url', 'wp_post_id', 'supporting_articles_count',
                'has_gaps', 'seo_score', 'word_count', 'last_updated',
                'topic_suggestions', 'content_gap_score', 'priority'
            ]
            
            for field in required_fields:
                self.assertIn(field, page, f"Missing field: {field}")
            
            # Verify topic suggestions structure
            topic_suggestions = page['topic_suggestions']
            self.assertIsInstance(topic_suggestions, list)
            self.assertEqual(len(topic_suggestions), 3)  # Should always return 3 suggestions
            
            if topic_suggestions:
                suggestion = topic_suggestions[0]
                suggestion_fields = ['id', 'topic', 'recommendation', 'type', 'estimated_word_count', 'priority']
                for field in suggestion_fields:
                    self.assertIn(field, suggestion, f"Missing suggestion field: {field}")
            
            # Verify data types
            self.assertIsInstance(page['supporting_articles_count'], int)
            self.assertIsInstance(page['has_gaps'], bool)
            self.assertIsInstance(page['seo_score'], int)
            self.assertIsInstance(page['content_gap_score'], (int, float))
            self.assertIn(page['priority'], ['high', 'medium', 'low'])
    
    def test_supporting_content_endpoint(self):
        """Test supporting content endpoint from PR #74."""
        url = f'/api/v1/sites/{self.site.id}/pages/{self.money_page1.id}/supporting-content/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Verify response structure
        self.assertIn('money_page', data)
        self.assertIn('supporting_pages', data)
        self.assertIn('supporting_count', data)
        self.assertIn('gap_analysis', data)
        self.assertIn('recommended_topics', data)
        self.assertIn('content_health_score', data)
        
        # Verify money page data
        money_page = data['money_page']
        self.assertEqual(money_page['id'], str(self.money_page1.id))
        self.assertEqual(money_page['title'], self.money_page1.title)
        self.assertEqual(money_page['seo_score'], 85)
        
        # Verify supporting pages
        supporting_pages = data['supporting_pages']
        self.assertEqual(len(supporting_pages), 1)  # money_page1 has 1 supporting page
        self.assertEqual(data['supporting_count'], 1)
        
        if supporting_pages:
            supporting_page = supporting_pages[0]
            self.assertIn('id', supporting_page)
            self.assertIn('title', supporting_page)
            self.assertIn('content_quality', supporting_page)
            self.assertIn('relevance_score', supporting_page)
            self.assertIn(supporting_page['content_quality'], ['excellent', 'good', 'fair', 'poor'])
    
    def test_add_to_pipeline(self):
        """Test add to pipeline functionality."""
        url = f'/api/v1/sites/{self.site.id}/pages/{self.money_page3.id}/add-to-pipeline/'
        payload = {
            'topic': 'Content Marketing Strategy Guide',
            'recommendation': 'Create comprehensive guide covering content planning, creation, and distribution',
            'priority': 'high'
        }
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('message', data)
        self.assertIn('content_job_id', data)
        self.assertIn('topic', data)
        self.assertIn('priority', data)
        self.assertIn('status', data)
        self.assertIn('estimated_completion', data)
        
        self.assertEqual(data['message'], 'Topic added to pipeline')
        self.assertEqual(data['topic'], payload['topic'])
        self.assertEqual(data['priority'], payload['priority'])
        self.assertEqual(data['status'], 'pending')
        
        # Verify content job was created
        content_job = ContentJob.objects.get(id=data['content_job_id'])
        self.assertEqual(content_job.job_type, 'supporting_content')
        self.assertEqual(content_job.topic, payload['topic'])
        self.assertEqual(content_job.page, self.money_page3)
        self.assertEqual(content_job.created_by, self.user)
    
    def test_add_to_pipeline_validation(self):
        """Test add to pipeline validation."""
        url = f'/api/v1/sites/{self.site.id}/pages/{self.money_page3.id}/add-to-pipeline/'
        
        # Test missing topic
        response = self.client.post(url, {'recommendation': 'test'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.json())
        self.assertEqual(response.json()['error'], 'Topic is required')
    
    def test_content_pipeline(self):
        """Test content pipeline endpoint."""
        # Create some content jobs first
        ContentJob.objects.create(
            site=self.site,
            page=self.money_page1,
            target_page=self.money_page1,
            job_type='supporting_content',
            topic='SEO Tips Guide',
            status='pending',
            created_by=self.user
        )
        
        ContentJob.objects.create(
            site=self.site,
            page=self.money_page2,
            target_page=self.money_page2,
            job_type='supporting_content',
            topic='PPC Best Practices',
            status='in_progress',
            created_by=self.user
        )
        
        url = f'/api/v1/sites/{self.site.id}/content-pipeline/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('pipeline', data)
        self.assertIn('total_jobs', data)
        self.assertIn('status_breakdown', data)
        self.assertIn('site_info', data)
        
        # Should have 2 jobs
        self.assertEqual(data['total_jobs'], 2)
        
        pipeline = data['pipeline']
        self.assertEqual(len(pipeline), 2)
        
        # Verify job structure
        for job in pipeline:
            self.assertIn('id', job)
            self.assertIn('topic', job)
            self.assertIn('status', job)
            self.assertIn('priority', job)
            self.assertIn('target_page', job)
            self.assertIn('created_at', job)
        
        # Verify status breakdown
        breakdown = data['status_breakdown']
        self.assertIn('pending', breakdown)
        self.assertIn('in_progress', breakdown)
        self.assertEqual(breakdown['pending'], 1)
        self.assertEqual(breakdown['in_progress'], 1)
    
    def test_topic_suggestions_generation(self):
        """Test topic suggestions generation for different scenarios."""
        url = f'/api/v1/sites/{self.site.id}/content-plan/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        content_plan = data['content_plan']
        
        # Find page with no supporting content (should have high priority suggestions)
        page_no_support = next((p for p in content_plan if p['supporting_articles_count'] == 0), None)
        if page_no_support:
            suggestions = page_no_support['topic_suggestions']
            
            # Should have exactly 3 suggestions
            self.assertEqual(len(suggestions), 3)
            
            # Should have FAQ and how-to suggestions for pages with no support
            suggestion_types = [s['type'] for s in suggestions]
            self.assertIn('faq', suggestion_types)
            self.assertIn('how_to', suggestion_types)
            
            # Should have high priority for urgent suggestions
            high_priority_count = sum(1 for s in suggestions if s['priority'] == 'high')
            self.assertGreaterEqual(high_priority_count, 2)
    
    def test_content_gap_score_calculation(self):
        """Test content gap score calculation."""
        url = f'/api/v1/sites/{self.site.id}/content-plan/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        content_plan = data['content_plan']
        
        # Page with no supporting content should have highest gap score
        page_no_support = next((p for p in content_plan if p['supporting_articles_count'] == 0), None)
        page_with_support = next((p for p in content_plan if p['supporting_articles_count'] > 0), None)
        
        if page_no_support and page_with_support:
            self.assertGreater(page_no_support['content_gap_score'], page_with_support['content_gap_score'])
            self.assertGreater(page_no_support['content_gap_score'], 50)  # Should be high
    
    def test_priority_determination(self):
        """Test priority determination logic."""
        url = f'/api/v1/sites/{self.site.id}/content-plan/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        content_plan = data['content_plan']
        
        # Find page with no support and low SEO score (should be high priority)
        high_priority_page = next(
            (p for p in content_plan if p['supporting_articles_count'] == 0 and p['seo_score'] < 70), 
            None
        )
        
        if high_priority_page:
            self.assertEqual(high_priority_page['priority'], 'high')
        
        # Verify all priorities are valid
        for page in content_plan:
            self.assertIn(page['priority'], ['high', 'medium', 'low'])
    
    def test_min_supporting_threshold_filter(self):
        """Test filtering by minimum supporting articles threshold."""
        url = f'/api/v1/sites/{self.site.id}/content-plan/?min_supporting=1'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Should adjust threshold and show different results
        self.assertEqual(data['min_supporting_threshold'], 1)
        
        # Pages with gaps should be different with different threshold
        url_default = f'/api/v1/sites/{self.site.id}/content-plan/?min_supporting=2'
        response_default = self.client.get(url_default)
        data_default = response_default.json()
        
        # Different thresholds should show different gap counts
        self.assertNotEqual(data['pages_with_gaps'], data_default['pages_with_gaps'])
    
    def test_site_info_in_response(self):
        """Test site information is included in all responses."""
        endpoints = [
            f'/api/v1/sites/{self.site.id}/content-plan/',
            f'/api/v1/sites/{self.site.id}/pages/{self.money_page1.id}/supporting-content/',
            f'/api/v1/sites/{self.site.id}/content-pipeline/'
        ]
        
        for endpoint in endpoints:
            response = self.client.get(endpoint)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            data = response.json()
            
            self.assertIn('site_info', data)
            site_info = data['site_info']
            self.assertEqual(site_info['id'], self.site.id)
            self.assertEqual(site_info['name'], self.site.name)
            self.assertEqual(site_info['url'], self.site.url)
