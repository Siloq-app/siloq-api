"""
Tests for integrations app - WordPress plugin API endpoints.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_model():
    return get_user_model()


@pytest.fixture
def create_user(user_model):
    def _create_user(email="test@example.com", password="testpass123"):
        return user_model.objects.create_user(
            email=email,
            username=email,
            password=password
        )
    return _create_user


@pytest.fixture
def create_site(create_user):
    def _create_site(user=None, name="Test Site", url="https://example.com"):
        from sites.models import Site
        if user is None:
            user = create_user()
        return Site.objects.create(user=user, name=name, url=url)
    return _create_site


@pytest.fixture
def create_api_key(create_site):
    def _create_api_key(site=None, name="Test Key"):
        from sites.models import APIKey
        if site is None:
            site = create_site()
        full_key, key_prefix, key_hash = APIKey.generate_key()
        api_key = APIKey.objects.create(
            site=site,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix
        )
        return api_key, full_key
    return _create_api_key


@pytest.fixture
def api_key_client(api_client, create_api_key):
    api_key, full_key = create_api_key()
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {full_key}')
    return api_client, api_key


@pytest.mark.django_db
class TestAPIKeyVerification:
    
    def test_verify_api_key_success(self, api_key_client):
        client, api_key = api_key_client
        
        response = client.post('/api/v1/auth/verify')
        assert response.status_code == 200
        assert response.data['valid'] is True
        assert response.data['site_id'] == api_key.site.id
    
    def test_verify_api_key_invalid(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION='Bearer sk_siloq_invalid_key')
        
        response = api_client.post('/api/v1/auth/verify')
        assert response.status_code == 401


@pytest.mark.django_db
class TestPageSync:
    
    def test_sync_page_create(self, api_key_client):
        from seo.models import Page
        client, api_key = api_key_client
        
        response = client.post('/api/v1/pages/sync/', {
            'wp_post_id': 123,
            'url': 'https://example.com/test-page',
            'title': 'Test Page',
            'content': 'Test content',
            'status': 'publish',
            'slug': 'test-page'
        })
        assert response.status_code == 201
        assert response.data['created'] is True
        assert Page.objects.filter(wp_post_id=123).exists()
    
    def test_sync_page_update(self, api_key_client):
        from seo.models import Page
        client, api_key = api_key_client
        
        # Create initial page
        page = Page.objects.create(
            site=api_key.site,
            wp_post_id=123,
            url='https://example.com/test-page',
            title='Original Title',
            slug='test-page'
        )
        
        response = client.post('/api/v1/pages/sync/', {
            'wp_post_id': 123,
            'url': 'https://example.com/test-page',
            'title': 'Updated Title',
            'status': 'publish',
            'slug': 'test-page'
        })
        assert response.status_code == 200
        assert response.data['created'] is False
        page.refresh_from_db()
        assert page.title == 'Updated Title'
    
    def test_sync_page_missing_required_fields(self, api_key_client):
        client, api_key = api_key_client
        
        response = client.post('/api/v1/pages/sync/', {
            'title': 'Test Page'
        })
        assert response.status_code == 400
    
    def test_sync_page_unauthorized(self, api_client):
        response = api_client.post('/api/v1/pages/sync/', {
            'wp_post_id': 123,
            'url': 'https://example.com/test-page',
            'title': 'Test Page',
            'slug': 'test-page'
        })
        assert response.status_code == 401


@pytest.mark.django_db
class TestSEODataSync:
    
    def test_sync_seo_data_create(self, api_key_client, create_site):
        from seo.models import Page, SEOData
        client, api_key = api_key_client
        
        page = Page.objects.create(
            site=api_key.site,
            wp_post_id=123,
            url='https://example.com/test-page',
            title='Test Page',
            slug='test-page'
        )
        
        response = client.post(f'/api/v1/pages/{page.id}/seo-data/', {
            'meta_title': 'SEO Title',
            'meta_description': 'SEO Description',
            'h1_count': 1,
            'h1_text': 'Main Heading',
            'seo_score': 85,
            'issues': [{'type': 'missing_meta', 'severity': 'high'}]
        })
        assert response.status_code == 201
        assert response.data['created'] is True
        assert SEOData.objects.filter(page=page).exists()
    
    def test_sync_seo_data_update(self, api_key_client, create_site):
        from seo.models import Page, SEOData
        client, api_key = api_key_client
        
        page = Page.objects.create(
            site=api_key.site,
            wp_post_id=123,
            url='https://example.com/test-page',
            title='Test Page',
            slug='test-page'
        )
        
        SEOData.objects.create(
            page=page,
            meta_title='Old Title',
            seo_score=70
        )
        
        response = client.post(f'/api/v1/pages/{page.id}/seo-data/', {
            'meta_title': 'New Title',
            'seo_score': 90
        })
        assert response.status_code == 200
        assert response.data['created'] is False
        page.seo_data.refresh_from_db()
        assert page.seo_data.meta_title == 'New Title'
        assert page.seo_data.seo_score == 90
    
    def test_sync_seo_data_page_not_found(self, api_key_client):
        client, api_key = api_key_client
        
        response = client.post('/api/v1/pages/999/seo-data/', {
            'seo_score': 85
        })
        assert response.status_code == 404
    
    def test_sync_seo_data_other_site_page(self, api_key_client, create_site, create_user):
        from seo.models import Page
        from sites.models import Site
        client, api_key = api_key_client
        
        other_user = create_user(email='other@example.com')
        other_site = Site.objects.create(user=other_user, name='Other Site', url='https://other.com')
        other_page = Page.objects.create(
            site=other_site,
            wp_post_id=456,
            url='https://other.com/page',
            title='Other Page',
            slug='other-page'
        )
        
        response = client.post(f'/api/v1/pages/{other_page.id}/seo-data/', {
            'seo_score': 85
        })
        assert response.status_code == 404


@pytest.mark.django_db
class TestScanEndpoints:
    
    def test_create_scan(self, api_key_client):
        from integrations.models import Scan
        client, api_key = api_key_client
        
        response = client.post('/api/v1/scans/', {
            'url': 'https://example.com',
            'scan_type': 'full'
        })
        assert response.status_code == 201
        assert response.data['status'] == 'completed'
        assert Scan.objects.filter(site=api_key.site).exists()
    
    def test_create_scan_default_type(self, api_key_client):
        client, api_key = api_key_client
        
        response = client.post('/api/v1/scans/', {
            'url': 'https://example.com'
        })
        assert response.status_code == 201
        assert response.data['scan_type'] == 'full'
    
    def test_get_scan(self, api_key_client):
        from integrations.models import Scan
        client, api_key = api_key_client
        
        scan = Scan.objects.create(
            site=api_key.site,
            url='https://example.com',
            scan_type='full',
            status='completed',
            score=75
        )
        
        response = client.get(f'/api/v1/scans/{scan.id}/')
        assert response.status_code == 200
        assert response.data['id'] == scan.id
        assert response.data['score'] == 75
    
    def test_get_scan_report_completed(self, api_key_client):
        from integrations.models import Scan
        client, api_key = api_key_client
        
        scan = Scan.objects.create(
            site=api_key.site,
            url='https://example.com',
            scan_type='full',
            status='completed',
            score=75,
            results={
                'technical_score': 80,
                'issues': [{'type': 'test_issue'}],
                'recommendations': ['Fix issue']
            }
        )
        
        response = client.get(f'/api/v1/scans/{scan.id}/report/')
        assert response.status_code == 200
        assert response.data['scan_id'] == scan.id
        assert 'keyword_cannibalization' in response.data
    
    def test_get_scan_report_not_completed(self, api_key_client):
        from integrations.models import Scan
        client, api_key = api_key_client
        
        scan = Scan.objects.create(
            site=api_key.site,
            url='https://example.com',
            scan_type='full',
            status='pending'
        )
        
        response = client.get(f'/api/v1/scans/{scan.id}/report/')
        assert response.status_code == 400
