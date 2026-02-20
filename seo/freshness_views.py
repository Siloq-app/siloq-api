"""
API endpoints for Freshness Alerts (Section 8).
"""
import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import FreshnessAlert

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


def _serialize_alert(a):
    return {
        'id': str(a.id),
        'page_url': a.page_url,
        'page_id': a.page_id,
        'page_type': a.page_type,
        'alert_level': a.alert_level,
        'days_since_modified': a.days_since_modified,
        'staleness_threshold': a.staleness_threshold,
        'alert_message': a.alert_message,
        'status': a.status,
        'snoozed_until': a.snoozed_until.isoformat() if a.snoozed_until else None,
        'has_traffic': a.has_traffic,
        'gsc_clicks_28d': a.gsc_clicks_28d,
        'created_at': a.created_at.isoformat(),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def freshness_alert_list(request):
    """GET /api/v1/freshness/alerts — List freshness alerts with filters."""
    site, err = _get_site_or_403(request)
    if err:
        return err

    qs = FreshnessAlert.objects.filter(site=site)

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)
    alert_level = request.query_params.get('alert_level')
    if alert_level:
        qs = qs.filter(alert_level=alert_level)

    # Pagination
    page = int(request.query_params.get('page', 1))
    per_page = int(request.query_params.get('per_page', 50))
    total = qs.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page
    items = qs.order_by('-created_at')[offset:offset + per_page]

    # By-level counts
    level_counts = FreshnessAlert.objects.filter(site=site).values('alert_level').annotate(
        count=Count('id'),
    )
    by_level = {lc['alert_level']: lc['count'] for lc in level_counts}

    return Response({
        'data': [_serialize_alert(a) for a in items],
        'meta': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'by_level': by_level,
        },
    })


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def freshness_alert_snooze(request, alert_id):
    """PUT /api/v1/freshness/alerts/{id}/snooze — Snooze alert for X days."""
    alert = get_object_or_404(FreshnessAlert, id=alert_id)
    if alert.site.user != request.user:
        return Response(
            {'error': {'code': 'FORBIDDEN', 'message': 'Permission denied', 'status': 403}},
            status=status.HTTP_403_FORBIDDEN,
        )

    days = request.data.get('days', 7)
    alert.snoozed_until = timezone.now() + timedelta(days=int(days))
    alert.status = 'snoozed'
    alert.save(update_fields=['snoozed_until', 'status', 'updated_at'])

    return Response({'data': _serialize_alert(alert)})
