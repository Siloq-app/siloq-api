"""
Tests for sites app - Site and APIKey management.
"""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


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
def authenticated_client(api_client, create_user):
    user = create_user()
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
    return api_client, user


@pytest.fixture
def create_site(create_user):
    def _create_site(user=None, name="Test Site", url="https://example.com"):
        from sites.models import Site
        if user is None:
            user = create_user()
        return Site.objects.create(user=user, name=name, url=url)
    return _create_site


@pytest.mark.django_db
class TestSiteManagement:
    
    def test_list_sites(self, authenticated_client, create_site):
        client, user = authenticated_client
        site = create_site(user=user)
        
        response = client.get('/api/v1/sites/')
        assert response.status_code == 200
        assert len(response.data['results']) == 1
        assert response.data['results'][0]['name'] == site.name
    
    def test_create_site(self, authenticated_client):
        from sites.models import Site
        client, user = authenticated_client
        
        response = client.post(
            '/api/v1/sites/',
            data={'name': 'New Site', 'url': 'https://newsite.com'},
            format='json'
        )
        assert response.status_code == 201
        assert Site.objects.filter(name='New Site').exists()
    
    def test_create_site_duplicate_url(self, authenticated_client, create_site):
        client, user = authenticated_client
        create_site(user=user, url='https://duplicate.com')
        
        response = client.post(
            '/api/v1/sites/',
            data={'name': 'Another Site', 'url': 'https://duplicate.com'},
            format='json'
        )
        assert response.status_code == 400
    
    def test_get_site_detail(self, authenticated_client, create_site):
        client, user = authenticated_client
        site = create_site(user=user)
        
        response = client.get(f'/api/v1/sites/{site.id}/')
        assert response.status_code == 200
        assert response.data['name'] == site.name
    
    def test_update_site(self, authenticated_client, create_site):
        client, user = authenticated_client
        site = create_site(user=user)
        
        response = client.put(
            f'/api/v1/sites/{site.id}/',
            data={'name': 'Updated Site', 'url': site.url},
            format='json'
        )
        assert response.status_code == 200
        site.refresh_from_db()
        assert site.name == 'Updated Site'
    
    def test_delete_site(self, authenticated_client, create_site):
        from sites.models import Site
        client, user = authenticated_client
        site = create_site(user=user)
        
        response = client.delete(f'/api/v1/sites/{site.id}/')
        assert response.status_code == 204
        assert not Site.objects.filter(id=site.id).exists()
    
    def test_site_overview(self, authenticated_client, create_site):
        client, user = authenticated_client
        site = create_site(user=user)
        
        response = client.get(f'/api/v1/sites/{site.id}/overview/')
        assert response.status_code == 200
        assert response.data['site_id'] == site.id
        assert 'health_score' in response.data
        assert 'total_pages' in response.data
    
    def test_cannot_access_other_user_site(self, authenticated_client, create_user):
        from sites.models import Site
        other_user = create_user(email='other@example.com')
        other_site = Site.objects.create(user=other_user, name='Other Site', url='https://other.com')
        
        client, _ = authenticated_client
        response = client.get(f'/api/v1/sites/{other_site.id}/')
        assert response.status_code == 404


@pytest.mark.django_db
class TestAPIKeyManagement:
    
    def test_list_api_keys(self, authenticated_client, create_site):
        from sites.models import APIKey
        client, user = authenticated_client
        site = create_site(user=user)
        
        # Create an API key
        APIKey.objects.create(
            site=site,
            name='Test Key',
            key_hash='somehash',
            key_prefix='sk_siloq_...'
        )
        
        response = client.get('/api/v1/api-keys/')
        assert response.status_code == 200
        assert len(response.data['results']) == 1
    
    def test_create_api_key(self, authenticated_client, create_site):
        from sites.models import APIKey
        client, user = authenticated_client
        site = create_site(user=user)
        
        response = client.post(
            '/api/v1/api-keys/',
            data={'name': 'New API Key', 'site_id': site.id},
            format='json'
        )
        assert response.status_code == 201
        assert 'key' in response.data
        assert APIKey.objects.filter(site=site).exists()
    
    def test_create_api_key_missing_site_id(self, authenticated_client):
        client, _ = authenticated_client
        
        response = client.post(
            '/api/v1/api-keys/',
            data={'name': 'New API Key'},
            format='json'
        )
        assert response.status_code == 400
    
    def test_create_api_key_other_user_site(self, authenticated_client, create_user):
        from sites.models import Site
        other_user = create_user(email='other@example.com')
        other_site = Site.objects.create(user=other_user, name='Other Site', url='https://other.com')
        
        client, _ = authenticated_client
        response = client.post(
            '/api/v1/api-keys/',
            data={'name': 'New API Key', 'site_id': other_site.id},
            format='json'
        )
        assert response.status_code == 404
    
    def test_revoke_api_key(self, authenticated_client, create_site):
        from sites.models import APIKey
        client, user = authenticated_client
        site = create_site(user=user)
        
        api_key = APIKey.objects.create(
            site=site,
            name='Test Key',
            key_hash='somehash',
            key_prefix='sk_siloq_...'
        )
        
        response = client.delete(f'/api/v1/api-keys/{api_key.id}/')
        assert response.status_code == 200
        api_key.refresh_from_db()
        assert not api_key.is_active
