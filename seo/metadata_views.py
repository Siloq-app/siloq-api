"""
API endpoints for Page Metadata (Section 9).
"""
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import PageMetadata

logger = logging.getLogger(__name__)


def _get_site_or_403(request):
    site_id = request.query_params.get('site_id') or request.data.get('site_id')
    if not site_id:
        return None, Response(
            {'error': {'code': 'SITE_NOT_FOUND', 'message': 'site_id is required', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    site = get_object_or_404(Site, id=site_id)
    if site.user != request.user:
        return None, Response(
            {'error': {'code': 'FORBIDDEN', 'message': 'Permission denied', 'status': 403}},
            status=status.HTTP_403_FORBIDDEN,
        )
    return site, None


def _serialize_page_metadata(pm):
    return {
        'id': str(pm.id),
        'page_url': pm.page_url,
        'page_id': pm.page_id,
        'post_type': pm.post_type,
        'title_tag': pm.title_tag,
        'h1_tag': pm.h1_tag,
        'meta_description': pm.meta_description,
        'canonical_url': pm.canonical_url,
        'http_status': pm.http_status,
        'is_indexable': pm.is_indexable,
        'noindex_source': pm.noindex_source,
        'silo_id': str(pm.silo_id) if pm.silo_id else None,
        'url_depth': pm.url_depth,
        'word_count': pm.word_count,
        'has_schema_markup': pm.has_schema_markup,
        'internal_links_in': pm.internal_links_in,
        'internal_links_out': pm.internal_links_out,
        'last_crawled': pm.last_crawled.isoformat() if pm.last_crawled else None,
        'last_modified': pm.last_modified.isoformat() if pm.last_modified else None,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pages_crawl(request):
    """POST /api/v1/pages/crawl — Trigger site crawl (async stub)."""
    site, err = _get_site_or_403(request)
    if err:
        return err

    # Check for in-progress crawl
    # (Simple stub — real implementation would use a job queue)
    return Response({
        'data': {
            'status': 'running',
            'site_id': site.id,
            'message': 'Site crawl started. Metadata will be updated as pages are processed.',
            'started_at': timezone.now().isoformat(),
        },
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pages_metadata_list(request):
    """GET /api/v1/pages/metadata — List page metadata with filters."""
    site, err = _get_site_or_403(request)
    if err:
        return err

    qs = PageMetadata.objects.filter(site=site)

    # Filters
    is_indexable = request.query_params.get('is_indexable')
    if is_indexable is not None:
        qs = qs.filter(is_indexable=is_indexable.lower() in ('true', '1'))
    http_status_filter = request.query_params.get('http_status')
    if http_status_filter:
        qs = qs.filter(http_status=int(http_status_filter))
    post_type = request.query_params.get('post_type')
    if post_type:
        qs = qs.filter(post_type=post_type)
    silo_id = request.query_params.get('silo_id')
    if silo_id:
        qs = qs.filter(silo_id=silo_id)

    # Pagination
    page = int(request.query_params.get('page', 1))
    per_page = int(request.query_params.get('per_page', 50))
    total = qs.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page
    items = qs.order_by('-last_crawled', '-created_at')[offset:offset + per_page]

    return Response({
        'data': [_serialize_page_metadata(pm) for pm in items],
        'meta': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
        },
    })
