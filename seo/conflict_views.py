"""
API endpoints for Cannibalization Conflicts (spec §3).
"""
import logging
import math
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import (
    CannibalizationConflict, ConflictPage, ConflictResolution,
    RedirectRegistry, KeywordAssignment, KeywordAssignmentHistory,
)
from integrations.wordpress_webhook import send_webhook_to_wordpress

logger = logging.getLogger(__name__)


def _get_site_or_error(request, site_id):
    """Validate site ownership."""
    site = get_object_or_404(Site, id=site_id)
    if site.user != request.user:
        return None, Response({
            'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'detail': None, 'status': 403}
        }, status=status.HTTP_403_FORBIDDEN)
    return site, None


def _serialize_conflict(conflict):
    """Serialize a CannibalizationConflict with its pages."""
    pages = conflict.pages.all().order_by('-is_recommended_winner', '-gsc_impressions')
    winner = pages.filter(is_recommended_winner=True).first()
    
    # Build flip-flop data if detected
    flip_flop = None
    if conflict.flip_flop_detected:
        flip_flop = {
            'detected': True,
            'correlation': float(conflict.flip_flop_correlation) if conflict.flip_flop_correlation else None,
            'position_volatility': float(conflict.position_volatility) if conflict.position_volatility else None,
            'daily_positions': conflict.metadata.get('daily_positions', {}) if conflict.metadata else {},
        }
    
    return {
        'id': str(conflict.id),
        'keyword': conflict.keyword,
        'conflict_type': conflict.conflict_type,
        'conflict_subtype': getattr(conflict, 'conflict_subtype', 'active_conflict'),
        'severity': conflict.severity,
        'note': getattr(conflict, 'note', ''),
        'raw_score': float(conflict.raw_score),
        'adjusted_score': float(conflict.adjusted_score),
        'status': conflict.status,
        'resolution_type': conflict.resolution_type,
        'detected_at': conflict.detected_at.isoformat() if conflict.detected_at else None,
        'resolved_at': conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        'max_impressions': conflict.max_impressions,
        'shared_gsc_queries': conflict.shared_gsc_queries,
        'flip_flop': flip_flop,  # NEW: Flip-flop detection data
        'winner_recommendation': {
            'page_url': winner.page_url,
            'winner_score': float(winner.winner_score),
        } if winner else None,
        'pages': [
            {
                'id': str(p.id),
                'page_url': p.page_url,
                'page_id': p.page_id,
                'page_type': p.page_type,
                'gsc_impressions': p.gsc_impressions,
                'gsc_clicks': p.gsc_clicks,
                'gsc_avg_position': float(p.gsc_avg_position) if p.gsc_avg_position else None,
                'backlink_count': p.backlink_count,
                'is_recommended_winner': p.is_recommended_winner,
                'winner_score': float(p.winner_score),
                'is_indexable': p.is_indexable,
                'http_status': p.http_status,
            }
            for p in pages
        ],
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conflict_list(request):
    """
    GET /api/v1/conflicts?site_id={id}
    List cannibalization conflicts with filters and pagination.
    """
    site_id = request.query_params.get('site_id')
    if not site_id:
        return Response({
            'error': {'code': 'MISSING_PARAM', 'message': 'site_id is required.', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    site, err = _get_site_or_error(request, site_id)
    if err:
        return err

    qs = CannibalizationConflict.objects.filter(site=site).prefetch_related('pages')

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    severity = request.query_params.get('severity')
    if severity:
        qs = qs.filter(severity=severity)

    min_impressions = request.query_params.get('min_impressions')
    if min_impressions:
        qs = qs.filter(max_impressions__gte=int(min_impressions))

    hide_noindex = request.query_params.get('hide_noindex', '').lower() == 'true'
    hide_redirected = request.query_params.get('hide_redirected', '').lower() == 'true'

    if hide_noindex:
        noindex_ids = ConflictPage.objects.filter(
            conflict__site=site, is_indexable=False
        ).values_list('conflict_id', flat=True).distinct()
        qs = qs.exclude(id__in=noindex_ids)

    if hide_redirected:
        redirected_ids = ConflictPage.objects.filter(
            conflict__site=site, http_status__in=[301, 302, 308]
        ).values_list('conflict_id', flat=True).distinct()
        qs = qs.exclude(id__in=redirected_ids)

    qs = qs.order_by('-severity', '-adjusted_score', '-detected_at')

    # Pagination
    page = int(request.query_params.get('page', 1))
    per_page = min(int(request.query_params.get('per_page', 25)), 100)
    total = qs.count()
    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page
    conflicts = qs[offset:offset + per_page]

    # Severity summary
    severity_counts = {}
    for sev in ['critical', 'high', 'medium', 'low']:
        severity_counts[sev] = CannibalizationConflict.objects.filter(
            site=site, status='open', severity=sev
        ).count()

    return Response({
        'data': [_serialize_conflict(c) for c in conflicts],
        'meta': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'severity_summary': severity_counts,
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def conflict_resolve(request, conflict_id):
    """
    POST /api/v1/conflicts/{id}/resolve
    Execute a resolution action atomically.
    """
    conflict = get_object_or_404(CannibalizationConflict, id=conflict_id)
    site, err = _get_site_or_error(request, conflict.site_id)
    if err:
        return err

    if conflict.status == 'resolved':
        return Response({
            'error': {'code': 'ALREADY_RESOLVED', 'message': 'Conflict is already resolved.', 'detail': None, 'status': 409}
        }, status=status.HTTP_409_CONFLICT)

    data = request.data
    action_type = data.get('action_type')
    valid_actions = ['redirect', 'merge_redirect', 'differentiate', 'canonical', 'dismiss']
    if action_type not in valid_actions:
        return Response({
            'error': {'code': 'INVALID_ACTION', 'message': f'action_type must be one of {valid_actions}.', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    winner_url = data.get('winner_url')
    loser_url = data.get('loser_url')
    redirect_type = data.get('redirect_type', 301)
    update_internal_links = data.get('update_internal_links', True)
    reassign_keyword = data.get('reassign_keyword', True)
    approved_by = data.get('approved_by', request.user.email)

    actions_taken = {
        'redirect_created': False,
        'internal_links_updated': 0,
        'keyword_reassigned': False,
    }

    try:
        with transaction.atomic():
            redirect_obj = None

            # Step 1: Create redirect if applicable
            if action_type in ('redirect', 'merge_redirect') and winner_url and loser_url:
                redirect_obj, created = RedirectRegistry.objects.get_or_create(
                    site=site,
                    source_url=loser_url,
                    defaults={
                        'target_url': winner_url,
                        'redirect_type': redirect_type,
                        'reason': f'conflict_resolution_{action_type}',
                        'conflict': conflict,
                        'status': 'active',
                        'created_by': approved_by or 'siloq_system',
                    },
                )
                if not created:
                    redirect_obj.target_url = winner_url
                    redirect_obj.redirect_type = redirect_type
                    redirect_obj.conflict = conflict
                    redirect_obj.save()
                actions_taken['redirect_created'] = True

            # Step 1b: Push redirect to WordPress via plugin webhook
            if actions_taken['redirect_created'] and redirect_obj:
                try:
                    webhook_payload = {
                        'source_url': loser_url,
                        'target_url': winner_url,
                        'redirect_type': redirect_type,
                        'reason': f'conflict_resolution_{action_type}',
                    }
                    webhook_result = send_webhook_to_wordpress(site, 'redirect.create', webhook_payload)
                    actions_taken['webhook_pushed'] = webhook_result.get('success', False)
                    if not webhook_result.get('success'):
                        logger.warning(
                            'WordPress webhook failed for conflict %s redirect: %s',
                            conflict_id, webhook_result.get('error', 'unknown')
                        )
                except Exception as webhook_err:
                    logger.warning('WordPress webhook error for conflict %s: %s', conflict_id, str(webhook_err))
                    actions_taken['webhook_pushed'] = False

            # Step 2: Reassign keyword
            if reassign_keyword and winner_url:
                try:
                    ka = KeywordAssignment.objects.get(
                        site=site, keyword=conflict.keyword, status='active'
                    )
                    previous_url = ka.page_url
                    ka.page_url = winner_url
                    ka.updated_at = timezone.now()
                    ka.save()

                    KeywordAssignmentHistory.objects.create(
                        assignment=ka,
                        site=site,
                        keyword=conflict.keyword,
                        previous_url=previous_url,
                        new_url=winner_url,
                        action='reassign',
                        reason=f'Conflict resolution: {action_type}',
                        performed_by=approved_by,
                    )
                    actions_taken['keyword_reassigned'] = True
                except KeywordAssignment.DoesNotExist:
                    pass

            # Step 3: Log resolution
            resolution = ConflictResolution.objects.create(
                conflict=conflict,
                site=site,
                action_type=action_type,
                winner_url=winner_url,
                loser_url=loser_url,
                redirect=redirect_obj,
                redirect_type=redirect_type if redirect_obj else None,
                keyword_reassigned=actions_taken['keyword_reassigned'],
                previous_keyword_owner=loser_url,
                new_keyword_owner=winner_url,
                approved_by=approved_by,
                internal_links_updated=actions_taken['internal_links_updated'],
            )

            # Step 4: Update conflict status
            conflict.status = 'resolved'
            conflict.resolution_type = action_type
            conflict.resolved_at = timezone.now()
            conflict.resolved_by = approved_by
            conflict.save()

    except Exception as e:
        logger.exception('Conflict resolution failed for %s', conflict_id)
        return Response({
            'error': {'code': 'RESOLUTION_FAILED', 'message': str(e), 'detail': None, 'status': 500}
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'data': {
            'resolution_id': str(resolution.id),
            'conflict_id': str(conflict.id),
            'action_type': action_type,
            'status': 'resolved',
            'actions_taken': actions_taken,
            'resolved_at': conflict.resolved_at.isoformat(),
        }
    }, status=status.HTTP_200_OK)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def conflict_dismiss(request, conflict_id):
    """
    PUT /api/v1/conflicts/{id}/dismiss
    Dismiss a conflict with reason.
    """
    conflict = get_object_or_404(CannibalizationConflict, id=conflict_id)
    site, err = _get_site_or_error(request, conflict.site_id)
    if err:
        return err

    reason = request.data.get('reason', '')
    approved_by = request.data.get('approved_by', request.user.email)

    with transaction.atomic():
        ConflictResolution.objects.create(
            conflict=conflict,
            site=site,
            action_type='dismiss',
            approved_by=approved_by,
            merge_brief=reason,
        )
        conflict.status = 'dismissed'
        conflict.resolution_type = 'dismiss'
        conflict.resolved_at = timezone.now()
        conflict.resolved_by = approved_by
        conflict.save()

    return Response({
        'data': {
            'conflict_id': str(conflict.id),
            'status': 'dismissed',
            'reason': reason,
            'dismissed_at': conflict.resolved_at.isoformat(),
        }
    })
