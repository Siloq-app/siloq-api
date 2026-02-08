"""
Tests for accounts app authentication.
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


@pytest.mark.django_db
class TestAuthentication:
    
    def test_login_success(self, api_client, create_user):
        user = create_user()
        response = api_client.post('/api/v1/auth/login/', {
            'email': user.email,
            'password': 'testpass123'
        })
        assert response.status_code == 200
        assert 'token' in response.data
        assert 'user' in response.data
    
    def test_login_invalid_credentials(self, api_client, create_user):
        create_user()
        response = api_client.post('/api/v1/auth/login/', {
            'email': 'test@example.com',
            'password': 'wrongpassword'
        })
        assert response.status_code == 400
    
    def test_login_missing_fields(self, api_client):
        response = api_client.post('/api/v1/auth/login/', {
            'email': 'test@example.com'
        })
        assert response.status_code == 400
    
    def test_register_success(self, api_client):
        response = api_client.post('/api/v1/auth/register/', {
            'email': 'newuser@example.com',
            'password': 'securepass123',
            'name': 'New User'
        })
        assert response.status_code == 201
        assert 'token' in response.data
        assert User.objects.filter(email='newuser@example.com').exists()
    
    def test_register_duplicate_email(self, api_client, create_user):
        user = create_user(email='duplicate@example.com')
        response = api_client.post('/api/v1/auth/register/', {
            'email': user.email,
            'password': 'securepass123'
        })
        assert response.status_code == 400
    
    def test_register_short_password(self, api_client):
        response = api_client.post('/api/v1/auth/register/', {
            'email': 'test@example.com',
            'password': 'short'
        })
        assert response.status_code == 400
    
    def test_me_endpoint_authenticated(self, authenticated_client):
        client, user = authenticated_client
        response = client.get('/api/v1/auth/me/')
        assert response.status_code == 200
        assert response.data['user']['email'] == user.email
    
    def test_me_endpoint_unauthenticated(self, api_client):
        response = api_client.get('/api/v1/auth/me/')
        assert response.status_code == 401
    
    def test_logout_success(self, authenticated_client):
        client, user = authenticated_client
        refresh = RefreshToken.for_user(user)
        response = client.post('/api/v1/auth/logout/', {
            'refresh_token': str(refresh)
        })
        assert response.status_code == 200
