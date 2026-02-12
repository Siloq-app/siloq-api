"""
Authentication views for dashboard users.
Handles login, register, logout, and user profile.
"""
import logging
import os

from dotenv import load_dotenv
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model

from .serializers import LoginSerializer, RegisterSerializer, UserSerializer

load_dotenv()
User = get_user_model()
logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    User login endpoint.
    
    POST /api/v1/auth/login
    Body: { "email": "user@example.com", "password": "password123" }
    
    Returns: { "token": "...", "user": {...} }
    """
    serializer = LoginSerializer(data=request.data)
    
    if serializer.is_valid():
        user = serializer.validated_data['user']
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        
        return Response({
            'message': 'Login successful',
            'token': access_token,
            'user': UserSerializer(user).data
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    User registration endpoint.

    POST /api/v1/auth/register
    Body: { "email": "...", "password": "...", "name": "..." (optional) }

    Returns: { "message": "...", "token": "...", "user": {...} }
    """
    serializer = RegisterSerializer(data=request.data)

    if serializer.is_valid():
        user = serializer.save()

        # Generate JWT token so frontend can log in immediately
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        return Response({
            'message': 'Registration successful',
            'token': access_token,
            'user': UserSerializer(user).data
        }, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    """
    User logout endpoint.
    
    POST /api/v1/auth/logout
    Headers: Authorization: Bearer <token>
    
    Returns: { "message": "Logged out successfully" }
    """
    try:
        refresh_token = request.data.get('refresh_token')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        return Response({'message': 'Logged out successfully'}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.warning(f"Logout failed: {str(e)}")
        return Response({'error': 'Logout failed'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    """
    Get current authenticated user.
    
    GET /api/v1/auth/me
    Headers: Authorization: Bearer <token>
    
    Returns: { "user": {...} }
    """
    return Response({
        'user': UserSerializer(request.user).data
    })


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def verify(request):
    """
    Verify an API key (for WordPress plugin).
    
    GET/POST /api/v1/auth/verify
    Headers: Authorization: Bearer <api_key>
    
    Returns: { "valid": true, "site": {...} } on success
    Returns: { "valid": false, "error": "..." } on failure
    """
    from sites.models import APIKey
    
    # Extract API key from Authorization header
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    
    if not auth_header.startswith('Bearer '):
        return Response({
            'valid': False,
            'error': 'Missing or invalid Authorization header. Expected: Bearer <api_key>'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    api_key = auth_header[7:]  # Remove 'Bearer ' prefix
    
    if not api_key.startswith('sk_siloq_'):
        return Response({
            'valid': False,
            'error': 'Invalid API key format. Keys should start with sk_siloq_'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Hash the key and look it up
    key_hash = APIKey.hash_key(api_key)
    
    try:
        api_key_obj = APIKey.objects.select_related('site', 'site__user').get(
            key_hash=key_hash,
            is_active=True
        )
    except APIKey.DoesNotExist:
        return Response({
            'valid': False,
            'error': 'Invalid or revoked API key'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Check if expired
    if api_key_obj.expires_at and api_key_obj.expires_at < timezone.now():
        return Response({
            'valid': False,
            'error': 'API key has expired'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Mark key as used
    api_key_obj.mark_used()
    
    site = api_key_obj.site
    
    return Response({
        'valid': True,
        'site': {
            'id': site.id,
            'name': site.name,
            'url': site.url,
            'is_active': site.is_active,
        },
        'key': {
            'name': api_key_obj.name,
            'created_at': api_key_obj.created_at.isoformat(),
        }
    }, status=status.HTTP_200_OK)
