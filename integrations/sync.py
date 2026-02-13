"""
WordPress sync views.
Handles API key verification, page sync, and SEO data sync.
"""
import logging
import re

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from sites.models import Site, APIKey
from seo.models import Page, SEOData
from seo.serializers import PageSyncSerializer as SEOPageSyncSerializer
from .models import Scan
from .serializers import SEODataSyncSerializer, ScanCreateSerializer, ScanSerializer
from .permissions import IsAPIKeyAuthenticated, IsJWTOrAPIKeyAuthenticated
from .authentication import APIKeyAuthentication

logger = logging.getLogger(__name__)


def _sanitize_slug(s):
    """Ensure slug is valid for SlugField (alphanumeric, hyphens, underscores)."""
    if not s or not isinstance(s, str):
        return 'page'
    s = s.strip().lower()
    s = re.sub(r'[^a-z0-9_-]+', '-', s)
    return s[:500] or 'page'


@csrf_exempt
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


@csrf_exempt
@api_view(['POST'])
@authentication_classes([APIKeyAuthentication])
@permission_classes([IsAPIKeyAuthenticated])
def sync_page(request):
    """
    Sync a page from WordPress to Django backend.
    """
    logger.debug(f"sync_page called, user: {request.user}, auth: {request.auth}")
    logger.info(f"sync_page request.data keys: {list(request.data.keys()) if hasattr(request.data, 'keys') else type(request.data)}")
    site = request.auth['site']
    serializer = SEOPageSyncSerializer(data=request.data)
    
    if not serializer.is_valid():
        logger.warning(f"sync_page validation failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = dict(serializer.validated_data)
    data['slug'] = _sanitize_slug(data.get('slug') or '')
    
    # Handle wp_post_id - can be integer or string like "term_123" for taxonomy terms
    raw_wp_post_id = data['wp_post_id']
    if isinstance(raw_wp_post_id, str):
        if raw_wp_post_id.startswith('term_'):
            # Taxonomy term - use negative ID to distinguish from posts
            # term_123 -> -123
            try:
                wp_post_id = -int(raw_wp_post_id.replace('term_', ''))
            except ValueError:
                wp_post_id = hash(raw_wp_post_id) % 1000000 * -1  # Fallback
        else:
            # Try to parse as integer
            try:
                wp_post_id = int(raw_wp_post_id)
            except ValueError:
                wp_post_id = hash(raw_wp_post_id) % 1000000
    else:
        wp_post_id = raw_wp_post_id
    data['wp_post_id'] = wp_post_id
    
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
    
    # If this page is marked as homepage, clear homepage flag from other pages
    if data.get('is_homepage', False):
        Page.objects.filter(site=site, is_homepage=True).exclude(id=page.id).update(is_homepage=False)
    
    # Update site's last_synced_at
    site.last_synced_at = timezone.now()
    site.save(update_fields=['last_synced_at'])
    
    return Response({
        'page_id': page.id,
        'message': 'Page synced successfully',
        'created': created
    }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@csrf_exempt
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


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAPIKeyAuthenticated])
def create_scan(request):
    """
    Create a new website scan (for lead gen scanner).
    
    POST /api/v1/scans
    Headers: Authorization: Bearer <api_key>
    Body: { "url": "https://example.com", "scan_type": "full" }
    
    Returns: { "id": 1, "status": "pending", ... }
    """
    site = request.auth['site']
    serializer = ScanCreateSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    scan = Scan.objects.create(
        site=site,
        url=serializer.validated_data['url'],
        scan_type=serializer.validated_data.get('scan_type', 'full'),
        status='pending'
    )
    
    # TODO: Trigger async scan processing (Celery task, etc.)
    # For now, simulate immediate completion with dummy data
    scan.status = 'completed'
    scan.score = 72  # Dummy score
    scan.pages_analyzed = 1
    scan.scan_duration_seconds = 2.5
    scan.completed_at = timezone.now()
    scan.results = {
        'technical_score': 80,
        'content_score': 70,
        'structure_score': 75,
        'performance_score': 65,
        'seo_score': 72,
        'issues': [
            {'type': 'missing_meta_description', 'severity': 'high', 'message': 'Missing meta description'},
            {'type': 'no_h1', 'severity': 'medium', 'message': 'No H1 heading found'},
        ],
        'recommendations': [
            'Add a meta description',
            'Add an H1 heading',
        ]
    }
    scan.save()
    
    return Response(ScanSerializer(scan).data, status=status.HTTP_201_CREATED)


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAPIKeyAuthenticated])
def get_scan(request, scan_id):
    """
    Get scan status and results.
    
    GET /api/v1/scans/{scan_id}
    Headers: Authorization: Bearer <api_key>
    
    Returns: { "id": 1, "status": "completed", "score": 72, ... }
    """
    site = request.auth['site']
    scan = get_object_or_404(Scan, id=scan_id, site=site)
    
    return Response(ScanSerializer(scan).data)


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAPIKeyAuthenticated])
def get_scan_report(request, scan_id):
    """
    Get full scan report (for lead gen scanner full report).
    
    GET /api/v1/scans/{scan_id}/report
    Headers: Authorization: Bearer <api_key>
    
    Returns: Full detailed report with keyword cannibalization analysis, etc.
    """
    site = request.auth['site']
    scan = get_object_or_404(Scan, id=scan_id, site=site)
    
    if scan.status != 'completed':
        return Response(
            {'error': 'Scan not completed yet'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Build comprehensive report
    report = {
        'scan_id': scan.id,
        'url': scan.url,
        'score': scan.score,
        'pages_analyzed': scan.pages_analyzed,
        'scan_duration_seconds': scan.scan_duration_seconds,
        'completed_at': scan.completed_at,
        'results': scan.results,
        # Add keyword cannibalization analysis
        'keyword_cannibalization': {
            'issues_found': len(scan.results.get('issues', [])),
            'recommendations': scan.results.get('recommendations', []),
        }
    }
    
    return Response(report)


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsJWTOrAPIKeyAuthenticated])
def debug_user_pages(request):
    """
    DEBUG ONLY - Shows what pages the current authenticated user can see.
    """
    user = request.user
    user_sites = Site.objects.filter(user=user)
    pages = Page.objects.filter(site__in=user_sites)
    
    return Response({
        'authenticated_user': {
            'id': user.id,
            'email': user.email,
        },
        'user_sites': list(user_sites.values('id', 'name', 'url')),
        'user_sites_count': user_sites.count(),
        'pages_count': pages.count(),
        'pages_sample': list(pages.values('id', 'title', 'site_id')[:5]),
    })


@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def debug_page_count(request):
    """
    DEBUG ONLY - Remove after testing.
    Returns ALL sites with page count and ownership info.
    """
    from django.db.models import Count
    # Get ALL sites, including those with 0 pages
    sites = Site.objects.annotate(page_count=Count('pages')).values(
        'id', 'name', 'url', 'page_count', 'user_id', 'user__email', 'last_synced_at'
    ).order_by('id')
    
    # Optional: check pages for a specific site
    site_id = request.query_params.get('site_id')
    pages_sample = []
    if site_id:
        pages_sample = list(Page.objects.filter(site_id=site_id).values('id', 'title', 'url')[:5])
    
    return Response({
        'sites': list(sites),
        'total_pages': Page.objects.count(),
        'total_sites': Site.objects.count(),
        'pages_sample': pages_sample
    })
