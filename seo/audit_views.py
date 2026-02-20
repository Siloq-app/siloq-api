"""
API endpoints for Content Audit (Section 7).
"""
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import ContentAuditLog

logger = logging.getLogger(__name__)


def _get_site_or_403(request):
    site_id = request.data.get('site_id') or request.query_params.get('site_id')
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


def _serialize_audit(a):
    return {
        'id': str(a.id),
        'audit_type': a.audit_type,
        'status': a.status,
        'started_at': a.started_at.isoformat(),
        'completed_at': a.completed_at.isoformat() if a.completed_at else None,
        'total_pages_audited': a.total_pages_audited,
        'pages_healthy': a.pages_healthy,
        'pages_refresh': a.pages_refresh,
        'pages_monitor': a.pages_monitor,
        'pages_kill': a.pages_kill,
        'new_conflicts_found': a.new_conflicts_found,
        'conflicts_resolved_since_last': a.conflicts_resolved_since_last,
        'queue_items_created': a.queue_items_created,
        'error_message': a.error_message,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def audit_run(request):
    """POST /api/v1/audit/run — Trigger content audit (async stub)."""
    site, err = _get_site_or_403(request)
    if err:
        return err

    audit_type = request.data.get('audit_type', 'manual')

    audit = ContentAuditLog.objects.create(
        site=site,
        audit_type=audit_type,
        started_at=timezone.now(),
        status='running',
    )

    return Response({
        'data': {
            'audit_id': str(audit.id),
            'status': 'running',
            'message': 'Content audit started. Poll GET /api/v1/audit/{audit_id} for results.',
        },
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def audit_detail(request, audit_id):
    """GET /api/v1/audit/{audit_id} — Get audit results."""
    audit = get_object_or_404(ContentAuditLog, id=audit_id)
    if audit.site.user != request.user:
        return Response(
            {'error': {'code': 'FORBIDDEN', 'message': 'Permission denied', 'status': 403}},
            status=status.HTTP_403_FORBIDDEN,
        )

    return Response({'data': _serialize_audit(audit)})
