"""
Google OAuth authentication views.
Handles Google OAuth login flow and callback.
"""
import logging
import os
import urllib.parse

import requests
from dotenv import load_dotenv
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect

load_dotenv()
User = get_user_model()
logger = logging.getLogger(__name__)


def _is_valid_frontend_url(url):
    """Validate that redirect URL is from allowed frontend domains."""
    allowed_hosts = [
        'localhost',
        '127.0.0.1',
        'app.siloq.ai',
        'siloq.ai',
    ]
    try:
        parsed = urllib.parse.urlparse(url)
        # Must be http or https
        if parsed.scheme not in ('http', 'https'):
            return False
        # Check host against allowed list
        host = parsed.hostname or ''
        return any(
            host == allowed or host.endswith(f'.{allowed}')
            for allowed in allowed_hosts
        )
    except Exception:
        return False


@api_view(['GET'])
@permission_classes([AllowAny])
def google_login(request):
    """
    Initiate Google OAuth login flow.
    Redirects to Google's OAuth consent screen.
    
    GET /api/v1/auth/google/login/
    """
    # Get Google OAuth credentials from environment
    client_id = os.getenv('GOOGLE_CLIENT_ID', '')
    redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8000/api/v1/auth/google/callback/')
    
    if not client_id:
        return Response(
            {'error': 'Google OAuth not configured'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    # Build Google OAuth URL with proper URL encoding
    google_auth_url = 'https://accounts.google.com/o/oauth2/v2/auth'
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'offline',
        'prompt': 'consent',
    }

    auth_url = f"{google_auth_url}?{urllib.parse.urlencode(params)}"
    
    # Redirect to Google
    return HttpResponseRedirect(auth_url)


@api_view(['GET'])
@permission_classes([AllowAny])
def google_callback(request):
    """
    Handle Google OAuth callback.
    Exchanges code for tokens and creates/authenticates user.
    
    GET /api/v1/auth/google/callback/
    Query params: code, state, error (if failed)
    """
    # Check for error
    error = request.GET.get('error')
    if error:
        return Response(
            {'error': f'Google authentication failed: {error}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get authorization code
    code = request.GET.get('code')
    if not code:
        return Response(
            {'error': 'No authorization code received'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Exchange code for tokens
    client_id = os.getenv('GOOGLE_CLIENT_ID', '')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '')
    redirect_uri = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8000/api/v1/auth/google/callback/')
    
    if not client_id or not client_secret:
        return Response(
            {'error': 'Google OAuth not configured on server'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    # Exchange code for access token
    token_url = 'https://oauth2.googleapis.com/token'
    token_data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }
    
    try:
        token_response = requests.post(token_url, data=token_data)
        token_response.raise_for_status()
        tokens = token_response.json()
        
        # Get user info from Google
        userinfo_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
        headers = {'Authorization': f'Bearer {tokens["access_token"]}'}
        userinfo_response = requests.get(userinfo_url, headers=headers)
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
        
        email = userinfo.get('email')
        name = userinfo.get('name', '')
        google_id = userinfo.get('id', '')
        
        if not email:
            return Response(
                {'error': 'Could not get email from Google'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get or create user
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Create new user
            user = User.objects.create(
                email=email,
                name=name or email.split('@')[0],
                is_active=True
            )
            user.set_unusable_password()  # User authenticated via Google only
            user.save()
        
        # Generate JWT token
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        
        # Validate and construct safe frontend redirect URL
        frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
        if not _is_valid_frontend_url(frontend_url):
            logger.error(f"Invalid FRONTEND_URL configured: {frontend_url}")
            return Response(
                {'error': 'Invalid frontend URL configuration'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        redirect_params = {
            'token': access_token,
            'email': email,
            'name': user.name or '',
        }
        redirect_url = f"{frontend_url}/auth/callback?{urllib.parse.urlencode(redirect_params)}"
        
        return HttpResponseRedirect(redirect_url)
        
    except requests.RequestException as e:
        logger.error(f"Google OAuth request failed: {str(e)}")
        return Response(
            {'error': 'Failed to authenticate with Google'},
            status=status.HTTP_502_BAD_GATEWAY
        )
    except Exception:
        logger.exception("Unexpected error during Google authentication")
        return Response(
            {'error': 'Authentication error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
