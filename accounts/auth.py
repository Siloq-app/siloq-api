"""
Authentication views for dashboard users.
Handles login, register, logout, and user profile.
"""
import logging
import os

from datetime import timedelta

from dotenv import load_dotenv
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model

from billing.models import Subscription

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

        # Auto-create trial subscription so trial page limits are enforced
        Subscription.objects.get_or_create(
            user=user,
            defaults={
                'tier': 'free_trial',
                'status': 'trialing',
                'trial_started_at': timezone.now(),
                'trial_ends_at': timezone.now() + timedelta(days=10),
                'trial_pages_limit': 10,
                'trial_pages_used': 0,
            }
        )

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


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me(request):
    """
    Get or update current authenticated user.
    
    GET /api/v1/auth/me
    Headers: Authorization: Bearer <token>
    Returns: { "user": {...} }
    
    PATCH /api/v1/auth/me
    Headers: Authorization: Bearer <token>
    Body: { "name": "...", "first_name": "...", "last_name": "..." }
    Returns: { "user": {...} }
    """
    if request.method == 'GET':
        return Response({
            'user': UserSerializer(request.user).data
        })
    
    # PATCH - Update user profile
    user = request.user
    data = request.data
    
    # Handle 'name' field - split into first_name and last_name
    if 'name' in data:
        name = data['name'].strip()
        if ' ' in name:
            # Split on first space
            parts = name.split(' ', 1)
            user.first_name = parts[0]
            user.last_name = parts[1]
        else:
            # No space - treat as first name
            user.first_name = name
            user.last_name = ''
    
    # Allow direct first_name/last_name updates (override 'name' if provided)
    if 'first_name' in data:
        user.first_name = data['first_name'].strip()
    if 'last_name' in data:
        user.last_name = data['last_name'].strip()
    
    user.save()
    
    return Response({
        'user': UserSerializer(user).data,
        'message': 'Profile updated successfully'
    })


@api_view(['GET', 'POST'])
@authentication_classes([])  # Skip DRF auth - we handle API key manually
@permission_classes([AllowAny])
def verify(request):
    """
    Verify an API key (for WordPress plugin).
    
    Supports two key types:
    - Site keys (sk_siloq_...): Tied to a specific site
    - Account keys (ak_siloq_...): Master key for account, auto-creates sites
    
    GET/POST /api/v1/auth/verify
    Headers: Authorization: Bearer <api_key>
    
    Returns: { "valid": true, "site": {...} } on success
    Returns: { "valid": false, "error": "..." } on failure
    """
    from sites.models import APIKey, AccountKey
    
    # Extract API key from Authorization header
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    
    if not auth_header.startswith('Bearer '):
        return Response({
            'valid': False,
            'error': 'Missing or invalid Authorization header. Expected: Bearer <api_key>'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    api_key = auth_header[7:]  # Remove 'Bearer ' prefix
    
    # Check if it's an Account Key (master key)
    if api_key.startswith('ak_siloq_'):
        return _verify_account_key(api_key)
    
    # Check if it's a Site Key
    if api_key.startswith('sk_siloq_'):
        return _verify_site_key(api_key)
    
    return Response({
        'valid': False,
        'error': 'Invalid API key format. Keys should start with sk_siloq_ or ak_siloq_'
    }, status=status.HTTP_401_UNAUTHORIZED)


def _verify_site_key(api_key):
    """Verify a site-specific API key (sk_siloq_...)"""
    from sites.models import APIKey
    
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
        'key_type': 'site',
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


def _verify_account_key(api_key):
    """Verify an account-level API key (ak_siloq_...) - Master/Agency key"""
    from sites.models import AccountKey
    
    key_hash = AccountKey.hash_key(api_key)
    
    try:
        account_key_obj = AccountKey.objects.select_related('user').get(
            key_hash=key_hash,
            is_active=True
        )
    except AccountKey.DoesNotExist:
        return Response({
            'valid': False,
            'error': 'Invalid or revoked account key'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Check if expired
    if account_key_obj.expires_at and account_key_obj.expires_at < timezone.now():
        return Response({
            'valid': False,
            'error': 'Account key has expired'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Mark key as used
    account_key_obj.mark_used()
    
    user = account_key_obj.user
    
    return Response({
        'valid': True,
        'key_type': 'account',
        'account': {
            'user_id': user.id,
            'email': user.email,
            'name': getattr(user, 'name', '') or user.email,
        },
        'key': {
            'name': account_key_obj.name,
            'created_at': account_key_obj.created_at.isoformat(),
            'sites_created': account_key_obj.sites_created,
        },
        'capabilities': {
            'auto_create_sites': True,
            'unlimited_sites': True,
        }
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    """
    POST /api/v1/auth/reset-password/
    Body: { "email": "user@example.com" }

    Sends a password reset link. Always returns 200 to prevent email enumeration.
    Local dev: set EMAIL_BACKEND=console in .env — email prints to Django terminal.
    Production: sent via Resend SMTP.
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    from django.core.mail import send_mail
    from django.conf import settings
    from django.contrib.auth import get_user_model

    User = get_user_model()
    email = request.data.get('email', '').strip().lower()

    if not email:
        return Response({'error': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

    # Silently succeed even if email not found (prevent enumeration)
    try:
        user = User.objects.get(email=email)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        frontend_url = getattr(settings, 'FRONTEND_URL', 'https://app.siloq.ai')
        reset_url = f"{frontend_url}/reset-password?uid={uid}&token={token}"

        send_mail(
            subject='Reset your Siloq password',
            message=(
                f"Hi {user.email},\n\n"
                f"Click the link below to reset your password. This link expires in 24 hours.\n\n"
                f"{reset_url}\n\n"
                f"If you didn't request this, you can ignore this email.\n\n"
                f"— The Siloq Team"
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@siloq.ai'),
            recipient_list=[user.email],
            fail_silently=True,
        )
    except User.DoesNotExist:
        pass  # Don't reveal whether the email exists

    return Response({
        'message': 'If that email is registered, a reset link has been sent.'
    }, status=status.HTTP_200_OK)


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def confirm_password_reset(request):
    """
    POST /api/v1/auth/reset-password/confirm/
    Body: { "uid": "...", "token": "...", "new_password": "..." }

    Validates the reset token and sets the new password.
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_str
    from django.utils.http import urlsafe_base64_decode
    from django.contrib.auth import get_user_model

    User = get_user_model()
    uid = request.data.get('uid', '')
    token = request.data.get('token', '')
    new_password = request.data.get('new_password', '')

    if not uid or not token or not new_password:
        return Response({'error': 'uid, token, and new_password are required.'}, status=status.HTTP_400_BAD_REQUEST)

    if len(new_password) < 8:
        return Response({'error': 'Password must be at least 8 characters.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user_pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_pk)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return Response({'error': 'Invalid reset link.'}, status=status.HTTP_400_BAD_REQUEST)

    if not default_token_generator.check_token(user, token):
        return Response({'error': 'Reset link is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save()

    return Response({'message': 'Password reset successfully. You can now log in.'}, status=status.HTTP_200_OK)
