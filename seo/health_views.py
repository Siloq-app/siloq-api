"""
API endpoints for Content Health Scores (spec §4).
"""
import logging
import math
import uuid
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import ContentHealthScore, ContentAuditLog

logger = logging.getLogger(__name__)


def _get_site_or_error(request, site_id):
    site = get_object_or_404(Site, id=site_id)
    if site.user != request.user:
        return None, Response({
            'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'detail': None, 'status': 403}
        }, status=status.HTTP_403_FORBIDDEN)
    return site, None


def _serialize_health_score(hs):
    return {
        'id': str(hs.id),
        'page_url': hs.page_url,
        'page_id': hs.page_id,
        'health_score': hs.health_score,
        'health_status': hs.health_status,
        'components': {
            'impressions': hs.impressions_score,
            'clicks': hs.clicks_score,
            'position': hs.position_score,
            'freshness': hs.freshness_score,
            'backlinks': hs.backlink_score,
            'internal_links': hs.internal_link_score,
        },
        'raw_data': {
            'gsc_impressions': hs.gsc_impressions,
            'gsc_clicks': hs.gsc_clicks,
            'gsc_avg_position': float(hs.gsc_avg_position) if hs.gsc_avg_position else None,
            'days_since_modified': hs.days_since_modified,
            'backlink_count': hs.backlink_count,
            'internal_links_in': hs.internal_links_in,
        },
        'recommended_action': hs.recommended_action,
        'recommended_action_reason': hs.recommended_action_reason,
        'previous_score': hs.previous_score,
        'score_change': hs.score_change,
        'scored_at': hs.scored_at.isoformat() if hs.scored_at else None,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def health_score_list(request):
    """
    GET /api/v1/health/scores?site_id={id}
    List health scores with filters, sorting, and pagination.
    """
    site_id = request.query_params.get('site_id')
    if not site_id:
        return Response({
            'error': {'code': 'MISSING_PARAM', 'message': 'site_id is required.', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    site, err = _get_site_or_error(request, site_id)
    if err:
        return err

    qs = ContentHealthScore.objects.filter(site=site)

    # Filters
    health_status = request.query_params.get('health_status')
    if health_status:
        qs = qs.filter(health_status=health_status)

    recommended_action = request.query_params.get('recommended_action')
    if recommended_action:
        qs = qs.filter(recommended_action=recommended_action)

    min_score = request.query_params.get('min_score')
    if min_score:
        qs = qs.filter(health_score__gte=int(min_score))

    max_score = request.query_params.get('max_score')
    if max_score:
        qs = qs.filter(health_score__lte=int(max_score))

    # Sorting
    sort_field = request.query_params.get('sort', 'health_score')
    allowed_sorts = {
        'health_score': 'health_score',
        'scored_at': 'scored_at',
        'page_url': 'page_url',
        'score_change': 'score_change',
    }
    order_field = allowed_sorts.get(sort_field, 'health_score')
    order = request.query_params.get('order', 'asc')
    if order == 'desc':
        order_field = f'-{order_field}'
    qs = qs.order_by(order_field)

    # Pagination
    page = int(request.query_params.get('page', 1))
    per_page = min(int(request.query_params.get('per_page', 25)), 100)
    total = qs.count()
    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page
    scores = qs[offset:offset + per_page]

    # Summary stats
    from django.db.models import Avg, Count
    summary = ContentHealthScore.objects.filter(site=site).aggregate(
        avg_score=Avg('health_score'),
        total_pages=Count('id'),
    )
    status_counts = {}
    for row in ContentHealthScore.objects.filter(site=site).values('health_status').annotate(count=Count('id')):
        status_counts[row['health_status']] = row['count']

    return Response({
        'data': [_serialize_health_score(s) for s in scores],
        'meta': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'summary': {
                'avg_score': round(summary['avg_score'], 1) if summary['avg_score'] else 0,
                'total_pages': summary['total_pages'],
                'by_status': status_counts,
            },
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def health_score_now(request):
    """
    POST /api/v1/health/score-now
    Trigger on-demand health scoring run (async stub).
    """
    site_id = request.data.get('site_id')
    if not site_id:
        return Response({
            'error': {'code': 'MISSING_PARAM', 'message': 'site_id is required.', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    site, err = _get_site_or_error(request, site_id)
    if err:
        return err

    job_id = str(uuid.uuid4())

    # Create audit log entry as a placeholder for the async job
    ContentAuditLog.objects.create(
        site=site,
        audit_type='health_scoring',
        started_at=timezone.now(),
        status='running',
    )

    return Response({
        'data': {
            'job_id': job_id,
            'status': 'running',
            'message': 'Health scoring run initiated. Results will be available shortly.',
        }
    }, status=status.HTTP_202_ACCEPTED)
