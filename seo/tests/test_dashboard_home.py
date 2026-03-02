"""
Test cases for Dashboard Home endpoints (Section 11.2).
Tests 3-column layout with Fix Now, In Progress, and Done This Month columns.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from uuid import uuid4
from datetime import datetime, timedelta
from django.utils import timezone

from sites.models import Site
from seo.models import Page, SEOData, Conflict, ContentJob


class DashboardHomeTestCase(TestCase):
    """Test dashboard home endpoints with 3-column layout."""
    
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
        
        # Create money pages and regular pages
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
        
        self.regular_page1 = Page.objects.create(
            site=self.site,
            wp_post_id=3,
            url='https://example.com/blog/seo-tips',
            title='SEO Tips Blog',
            is_money_page=False
        )
        
        # Create SEO data with varying scores
        SEOData.objects.create(
            page=self.money_page1,
            seo_score=85,
            word_count=1200,
            issues=[
                {'type': 'missing_meta_description', 'severity': 'medium', 'message': 'Missing meta description'}
            ]
        )
        
        SEOData.objects.create(
            page=self.money_page2,
            seo_score=35,  # Critical issue
            word_count=600,
            issues=[
                {'type': 'missing_h1', 'severity': 'high', 'message': 'Missing H1 tag'},
                {'type': 'thin_content', 'severity': 'high', 'message': 'Content too thin'}
            ]
        )
        
        SEOData.objects.create(
            page=self.regular_page1,
            seo_score=75,
            word_count=800
        )
        
        # Create conflicts with varying severity
        self.high_severity_conflict = Conflict.objects.create(
            site=self.site,
            page1=self.money_page1,
            page2=self.regular_page1,
            query_string='best seo services',
            severity_score=90,
            status='active',
            recommendation='Merge blog content into main service page'
        )
        
        self.medium_severity_conflict = Conflict.objects.create(
            site=self.site,
            page1=self.money_page2,
            page2=self.regular_page1,
            query_string='ppc management',
            severity_score=60,
            status='active',
            recommendation='Optimize PPC landing page'
        )
        
        # Create resolved conflict for Done column
        self.resolved_conflict = Conflict.objects.create(
            site=self.site,
            page1=self.money_page1,
            page2=self.money_page2,
            query_string='digital marketing',
            severity_score=75,
            status='resolved',
            resolved_at=timezone.now() - timedelta(days=5),
            winner_page=self.money_page1
        )
        
        # Create content jobs in different statuses
        self.approved_job = ContentJob.objects.create(
            site=self.site,
            page=self.money_page1,
            target_page=self.money_page1,
            job_type='supporting_content',
            topic='SEO Services FAQ',
            status='approved',
            approved_at=timezone.now() - timedelta(hours=2),
            approved_by=self.user,
            wp_post_id=123,
            wp_status='draft'
        )
        
        self.completed_job = ContentJob.objects.create(
            site=self.site,
            page=self.money_page2,
            target_page=self.money_page2,
            job_type='conflict_resolution',
            topic='PPC Landing Page Optimization',
            status='completed',
            completed_at=timezone.now() - timedelta(days=10),
            actual_word_count=1500
        )
        
        # Set up supporting content relationships
        self.money_page1.related_pages.add(self.regular_page1)
        # money_page2 has no supporting pages (content gap)
    
    def test_dashboard_home_structure(self):
        """Test dashboard home response structure."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Verify main structure
        required_keys = ['fix_now', 'in_progress', 'done_this_month', 'summary', 'site_info', 'generated_at']
        for key in required_keys:
            self.assertIn(key, data, f"Missing key: {key}")
        
        # Verify 3 columns
        self.assertIsInstance(data['fix_now'], list)
        self.assertIsInstance(data['in_progress'], list)
        self.assertIsInstance(data['done_this_month'], list)
        
        # Verify summary structure
        summary = data['summary']
        self.assertIn('current_month', summary)
        self.assertIn('last_month', summary)
        self.assertIn('month_over_month_change', summary)
        self.assertIn('active_items', summary)
        
        # Verify site info
        site_info = data['site_info']
        self.assertEqual(site_info['id'], str(self.site.id))
        self.assertEqual(site_info['name'], self.site.name)
        self.assertEqual(site_info['url'], self.site.url)
    
    def test_fix_now_column(self):
        """Test Fix Now column with actionable items."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        fix_now = data['fix_now']
        self.assertGreater(len(fix_now), 0)
        
        # Should include high severity conflicts
        conflict_items = [item for item in fix_now if item['type'] == 'conflict']
        self.assertGreater(len(conflict_items), 0)
        
        if conflict_items:
            conflict = conflict_items[0]
            self.assertEqual(conflict['priority'], 'critical')
            self.assertIn('action_text', conflict)
            self.assertIn('action_url', conflict)
            self.assertIn('severity_score', conflict)
            self.assertIn('estimated_impact', conflict)
            self.assertIn('time_to_resolve', conflict)
        
        # Should include critical page issues
        page_issue_items = [item for item in fix_now if item['type'] == 'page_issue']
        self.assertGreater(len(page_issue_items), 0)
        
        if page_issue_items:
            page_issue = page_issue_items[0]
            self.assertEqual(page_issue['priority'], 'high')
            self.assertIn('seo_score', page_issue)
            self.assertLess(page_issue['seo_score'], 50)
        
        # Should include content gaps
        content_gap_items = [item for item in fix_now if item['type'] == 'content_gap']
        if content_gap_items:
            content_gap = content_gap_items[0]
            self.assertEqual(content_gap['priority'], 'medium')
            self.assertIn('supporting_count', content_gap)
            self.assertLess(content_gap['supporting_count'], 2)
    
    def test_in_progress_column(self):
        """Test In Progress column with approved items."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        in_progress = data['in_progress']
        self.assertGreater(len(in_progress), 0)
        
        # Should include approved content jobs
        job_items = [item for item in in_progress if item['type'] == 'content_job']
        self.assertGreater(len(job_items), 0)
        
        if job_items:
            job = job_items[0]
            self.assertIn('wp_status', job)
            self.assertIn('live_status', job)
            self.assertIn('approved_at', job)
            self.assertIn('progress_percentage', job)
            self.assertIn('target_page', job)
            
            # Verify WordPress status
            self.assertIn(job['wp_status'], ['published', 'draft', 'pushed', 'pending_push', 'pending_approval'])
            self.assertIn(job['live_status'], ['live', 'draft', 'pushed_to_wp', 'pending_push', 'waiting_approval'])
    
    def test_done_this_month_column(self):
        """Test Done This Month column with resolved items."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        done_this_month = data['done_this_month']
        
        # Should include resolved conflicts
        conflict_items = [item for item in done_this_month if item['type'] == 'conflict_resolved']
        if conflict_items:
            conflict = conflict_items[0]
            self.assertIn('resolved_at', conflict)
            self.assertIn('resolution_type', conflict)
            self.assertIn('impact', conflict)
            self.assertEqual(conflict['resolution_type'], 'conflict_resolution')
        
        # Should include completed content jobs
        job_items = [item for item in done_this_month if item['type'] == 'content_completed']
        if job_items:
            job = job_items[0]
            self.assertIn('completed_at', job)
            self.assertIn('resolution_type', job)
            self.assertIn('word_count', job)
            self.assertIn(job['resolution_type'], ['conflict_resolution', 'supporting_content', 'money_page_optimization'])
    
    def test_dashboard_summary(self):
        """Test dashboard summary statistics."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        summary = data['summary']
        
        # Verify current month stats
        current_month = summary['current_month']
        self.assertIn('conflicts_resolved', current_month)
        self.assertIn('content_completed', current_month)
        self.assertIn('total_completed', current_month)
        
        # Verify last month stats
        last_month = summary['last_month']
        self.assertIn('conflicts_resolved', last_month)
        self.assertIn('content_completed', last_month)
        self.assertIn('total_completed', last_month)
        
        # Verify month-over-month change
        change = summary['month_over_month_change']
        self.assertIn('conflicts_resolved', change)
        self.assertIn('content_completed', change)
        self.assertIn('total_completed', change)
        
        # Verify active items
        active = summary['active_items']
        self.assertIn('conflicts_active', active)
        self.assertIn('jobs_in_progress', active)
        self.assertIn('money_pages_with_gaps', active)
        
        # Verify counts are reasonable
        self.assertGreaterEqual(current_month['total_completed'], 0)
        self.assertGreaterEqual(active['conflicts_active'], 0)
        self.assertGreaterEqual(active['money_pages_with_gaps'], 0)
    
    def test_priority_ordering_in_fix_now(self):
        """Test that Fix Now items are ordered by priority."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        fix_now = data['fix_now']
        if len(fix_now) > 1:
            # Check that critical items come before high, which come before medium
            priorities = [item['priority'] for item in fix_now]
            priority_order = {'critical': 0, 'high': 1, 'medium': 2}
            
            for i in range(len(priorities) - 1):
                current_priority = priority_order.get(priorities[i], 3)
                next_priority = priority_order.get(priorities[i + 1], 3)
                self.assertLessEqual(current_priority, next_priority, 
                    f"Items not ordered by priority: {priorities}")
    
    def test_month_over_month_calculation(self):
        """Test month-over-month change calculation."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        summary = data['summary']
        change = summary['month_over_month_change']
        
        # Verify change values are numbers
        for metric in ['conflicts_resolved', 'content_completed', 'total_completed']:
            self.assertIsInstance(change[metric], (int, float))
    
    def test_limit_parameter(self):
        """Test limit parameter for column items."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/?limit=2'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        # Each column should have at most 2 items
        for column in ['fix_now', 'in_progress', 'done_this_month']:
            self.assertLessEqual(len(data[column]), 2)
    
    def test_wordpress_status_integration(self):
        """Test WordPress status integration for content jobs."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        in_progress = data['in_progress']
        job_items = [item for item in in_progress if item['type'] == 'content_job']
        
        if job_items:
            job = job_items[0]
            # Should have WordPress status based on wp_post_id and wp_status
            self.assertIn(job['wp_status'], ['published', 'draft', 'pushed', 'pending_push'])
            
            # Progress should be calculated based on status
            self.assertIsInstance(job['progress_percentage'], (int, float))
            self.assertGreaterEqual(job['progress_percentage'], 0)
            self.assertLessEqual(job['progress_percentage'], 100)
    
    def test_content_gap_detection(self):
        """Test content gap detection for money pages."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        fix_now = data['fix_now']
        content_gap_items = [item for item in fix_now if item['type'] == 'content_gap']
        
        if content_gap_items:
            content_gap = content_gap_items[0]
            # Should identify money pages with <2 supporting articles
            self.assertLess(content_gap['supporting_count'], 2)
            self.assertEqual(content_gap['priority'], 'medium')
    
    def test_generated_at_timestamp(self):
        """Test that dashboard includes generation timestamp."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        self.assertIn('generated_at', data)
        # Should be a recent timestamp
        generated_time = timezone.datetime.fromisoformat(data['generated_at'].replace('Z', '+00:00'))
        self.assertIsInstance(generated_time, datetime)
    
    def test_severity_score_filtering(self):
        """Test that only high severity conflicts appear in Fix Now."""
        url = f'/api/v1/sites/{self.site.id}/dashboard/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        
        fix_now = data['fix_now']
        conflict_items = [item for item in fix_now if item['type'] == 'conflict']
        
        for conflict in conflict_items:
            # Should only include high severity conflicts (>=80)
            self.assertGreaterEqual(conflict['severity_score'], 80)
            self.assertEqual(conflict['priority'], 'critical')
