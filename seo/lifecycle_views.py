"""
API endpoints for Lifecycle Queue (spec §5).
"""
import logging
import math
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import (
    LifecycleQueue, RedirectRegistry, KeywordAssignment, KeywordAssignmentHistory,
)

logger = logging.getLogger(__name__)


def _get_site_or_error(request, site_id):
    site = get_object_or_404(Site, id=site_id)
    if site.user != request.user:
        return None, Response({
            'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'detail': None, 'status': 403}
        }, status=status.HTTP_403_FORBIDDEN)
    return site, None


def _serialize_queue_item(item):
    return {
        'id': str(item.id),
        'action_type': item.action_type,
        'priority': item.priority,
        'source_type': item.source_type,
        'source_id': str(item.source_id) if item.source_id else None,
        'primary_page_url': item.primary_page_url,
        'secondary_page_url': item.secondary_page_url,
        'recommendation_summary': item.recommendation_summary,
        'recommendation_detail': item.recommendation_detail,
        'status': item.status,
        'approved_by': item.approved_by,
        'approved_at': item.approved_at.isoformat() if item.approved_at else None,
        'completed_at': item.completed_at.isoformat() if item.completed_at else None,
        'execution_steps': item.execution_steps,
        'execution_errors': item.execution_errors,
        'created_at': item.created_at.isoformat() if item.created_at else None,
        'expires_at': item.expires_at.isoformat() if item.expires_at else None,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lifecycle_queue_list(request):
    """
    GET /api/v1/lifecycle/queue?site_id={id}
    List pending lifecycle actions with filters and pagination.
    """
    site_id = request.query_params.get('site_id')
    if not site_id:
        return Response({
            'error': {'code': 'MISSING_PARAM', 'message': 'site_id is required.', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    site, err = _get_site_or_error(request, site_id)
    if err:
        return err

    qs = LifecycleQueue.objects.filter(site=site)

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    priority = request.query_params.get('priority')
    if priority:
        qs = qs.filter(priority=priority)

    action_type = request.query_params.get('action_type')
    if action_type:
        qs = qs.filter(action_type=action_type)

    qs = qs.order_by('priority', '-created_at')

    # Pagination
    page = int(request.query_params.get('page', 1))
    per_page = min(int(request.query_params.get('per_page', 25)), 100)
    total = qs.count()
    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page
    items = qs[offset:offset + per_page]

    # Counts for meta
    by_priority = {}
    for row in LifecycleQueue.objects.filter(site=site).values('priority').annotate(count=Count('id')):
        by_priority[row['priority']] = row['count']

    by_action = {}
    for row in LifecycleQueue.objects.filter(site=site).values('action_type').annotate(count=Count('id')):
        by_action[row['action_type']] = row['count']

    return Response({
        'data': [_serialize_queue_item(i) for i in items],
        'meta': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'by_priority': by_priority,
            'by_action': by_action,
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def lifecycle_queue_execute(request, queue_id):
    """
    POST /api/v1/lifecycle/queue/{id}/execute
    Execute an approved lifecycle action with redirect creation,
    keyword registry update, internal link update, and verification.
    """
    item = get_object_or_404(LifecycleQueue, id=queue_id)
    site, err = _get_site_or_error(request, item.site_id)
    if err:
        return err

    if item.status == 'completed':
        return Response({
            'error': {'code': 'ALREADY_COMPLETED', 'message': 'This queue item is already completed.', 'detail': None, 'status': 409}
        }, status=status.HTTP_409_CONFLICT)

    if item.status not in ('pending', 'approved'):
        return Response({
            'error': {'code': 'INVALID_STATUS', 'message': f'Cannot execute item with status "{item.status}".', 'detail': None, 'status': 400}
        }, status=status.HTTP_400_BAD_REQUEST)

    approved_by = request.data.get('approved_by', request.user.email)
    execution_steps = []
    errors = []

    try:
        with transaction.atomic():
            # Step 1: Create redirect if action involves redirect
            if item.action_type in ('redirect', 'merge_redirect', 'kill') and item.secondary_page_url:
                try:
                    redirect_obj, created = RedirectRegistry.objects.get_or_create(
                        site=site,
                        source_url=item.primary_page_url,
                        defaults={
                            'target_url': item.secondary_page_url,
                            'redirect_type': 301,
                            'reason': f'lifecycle_{item.action_type}',
                            'status': 'active',
                            'created_by': approved_by,
                        },
                    )
                    execution_steps.append({
                        'step': 'redirect_created',
                        'status': 'success',
                        'detail': {
                            'source': item.primary_page_url,
                            'target': item.secondary_page_url,
                            'type': 301,
                            'created': created,
                        },
                    })
                except Exception as e:
                    errors.append({'step': 'redirect_created', 'error': str(e)})
                    execution_steps.append({'step': 'redirect_created', 'status': 'error', 'detail': str(e)})

            # Step 2: Keyword registry update
            try:
                reassigned = KeywordAssignment.objects.filter(
                    site=site, page_url=item.primary_page_url, status='active'
                )
                reassign_count = 0
                for ka in reassigned:
                    if item.secondary_page_url:
                        previous_url = ka.page_url
                        ka.page_url = item.secondary_page_url
                        ka.save()
                        KeywordAssignmentHistory.objects.create(
                            assignment=ka,
                            site=site,
                            keyword=ka.keyword,
                            previous_url=previous_url,
                            new_url=item.secondary_page_url,
                            action='reassign',
                            reason=f'Lifecycle execution: {item.action_type}',
                            performed_by=approved_by,
                        )
                        reassign_count += 1
                    else:
                        ka.status = 'deprecated'
                        ka.deprecated_at = timezone.now()
                        ka.save()
                        reassign_count += 1

                execution_steps.append({
                    'step': 'keyword_registry_updated',
                    'status': 'success',
                    'detail': {'keywords_affected': reassign_count},
                })
            except Exception as e:
                errors.append({'step': 'keyword_registry_updated', 'error': str(e)})
                execution_steps.append({'step': 'keyword_registry_updated', 'status': 'error', 'detail': str(e)})

            # Step 3: Internal link update (stub — real implementation would call WP API)
            execution_steps.append({
                'step': 'internal_links_updated',
                'status': 'pending',
                'detail': 'Internal link updates queued for next sync.',
            })

            # Step 4: Verification (stub)
            execution_steps.append({
                'step': 'verification',
                'status': 'pending',
                'detail': 'Verification scheduled.',
            })

            # Update queue item
            item.status = 'completed'
            item.approved_by = approved_by
            item.approved_at = item.approved_at or timezone.now()
            item.completed_at = timezone.now()
            item.execution_steps = execution_steps
            item.execution_errors = errors if errors else None
            item.save()

    except Exception as e:
        logger.exception('Lifecycle execution failed for %s', queue_id)
        return Response({
            'error': {'code': 'EXECUTION_FAILED', 'message': str(e), 'detail': None, 'status': 500}
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({
        'data': {
            'queue_id': str(item.id),
            'status': 'completed',
            'action_type': item.action_type,
            'execution_steps': execution_steps,
            'errors': errors if errors else None,
            'completed_at': item.completed_at.isoformat(),
        }
    })
