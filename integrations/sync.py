"""
WordPress sync views.
Handles API key verification, page sync, and SEO data sync.
"""
import logging
import re

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from django.utils import timezone
from django.shortcuts import get_object_or_404

from sites.models import Site, APIKey
from seo.models import Page, SEOData
from seo.serializers import PageSyncSerializer as SEOPageSyncSerializer
from .models import Scan
from .serializers import SEODataSyncSerializer
from .permissions import IsAPIKeyAuthenticated
from .authentication import APIKeyAuthentication

logger = logging.getLogger(__name__)


def _sanitize_slug(s):
    """Ensure slug is valid for SlugField (alphanumeric, hyphens, underscores)."""
    if not s or not isinstance(s, str):
        return 'page'
    s = s.strip().lower()
    s = re.sub(r'[^a-z0-9_-]+', '-', s)
    return s[:500] or 'page'


@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def verify_api_key(request):
    """
    Verify API key endpoint for WordPress plugin Test Connection.
    
    POST /api/v1/auth/verify
    Headers: Authorization: Bearer <api_key>   (api_key must be sk_siloq_...)
    
    Returns: { "authenticated": true, "valid": true, "site_id": ..., "site_name": "...", "site_url": "..." }
    WordPress plugin expects 200 and body.authenticated === true for success.
    """
    site = request.auth['site']
    
    return Response({
        'authenticated': True,
        'valid': True,
        'site_id': site.id,
        'site_name': site.name,
        'site_url': site.url,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def sync_page(request):
    """
    Sync a page from WordPress to Django backend.
    """
    logger.debug(f"sync_page called, user: {request.user}, auth: {request.auth}")
    site = request.auth['site']
    serializer = SEOPageSyncSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = dict(serializer.validated_data)
    data['slug'] = _sanitize_slug(data.get('slug') or '')
    
    # Get or create page
    wp_post_id = data['wp_post_id']
    page, created = Page.objects.get_or_create(
        site=site,
        wp_post_id=wp_post_id,
        defaults=data
    )
    
    if not created:
        # Update existing page
        for key, value in data.items():
            setattr(page, key, value)
        page.save()
    
    # Update site's last_synced_at
    site.last_synced_at = timezone.now()
    site.save(update_fields=['last_synced_at'])
    
    return Response({
        'page_id': page.id,
        'message': 'Page synced successfully',
        'created': created
    }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def sync_seo_data(request, page_id=None):
    """
    Sync SEO data for a page from WordPress scanner.
    
    POST /api/v1/pages/{page_id}/seo-data/
    Headers: Authorization: Bearer <api_key>
    Body: { "seo_score": 85, "issues": [...], ... }
    
    Returns: { "seo_data_id": 1, "message": "SEO data synced successfully" }
    """
    # Get page_id from URL parameter or request data
    page_id = page_id or request.data.get('page_id')
    if not page_id:
        return Response(
            {'error': 'page_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    site = request.auth['site']
    page = get_object_or_404(Page, id=page_id, site=site)
    
    serializer = SEODataSyncSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    # Get or create SEO data
    seo_data, created = SEOData.objects.get_or_create(
        page=page,
        defaults=serializer.validated_data
    )
    
    if not created:
        # Update existing SEO data
        for key, value in serializer.validated_data.items():
            setattr(seo_data, key, value)
        seo_data.save()
    
    return Response({
        'seo_data_id': seo_data.id,
        'message': 'SEO data synced successfully',
        'created': created
    }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
