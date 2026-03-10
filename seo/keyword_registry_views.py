"""
API endpoints for the Keyword Assignment Registry.
Spec: api-endpoint-spec.md — Section 1 (Keyword Registry)
"""
import logging
import math
import uuid

from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import (
    KeywordAssignment,
    KeywordAssignmentHistory,
    SiloDefinition,
    SiloKeyword,
    PageMetadata,
)
from seo.keyword_registry import (
    bootstrap_keyword_registry,
    check_keyword_available,
    get_keyword_owner,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_site_or_error(request, site_id=None):
    """Resolve site from body/param site_id or URL kwarg. Returns (site, error_response)."""
    sid = site_id or request.data.get('site_id') or request.query_params.get('site_id')
    if not sid:
        return None, Response(
            {'error': {'code': 'SITE_NOT_FOUND', 'message': 'site_id is required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        site = Site.objects.get(id=sid)
    except Site.DoesNotExist:
        return None, Response(
            {'error': {'code': 'SITE_NOT_FOUND', 'message': 'Invalid site_id.', 'status': 404}},
            status=status.HTTP_404_NOT_FOUND,
        )
    if site.user != request.user:
        return None, Response(
            {'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'status': 403}},
            status=status.HTTP_403_FORBIDDEN,
        )
    return site, None


def _build_match(ka, match_type='exact'):
    """Build a match dict from a KeywordAssignment."""
    silo_name = ''
    if ka.silo_id:
        try:
            silo_name = ka.silo.name
        except Exception:
            pass
    return {
        'type': match_type,
        'keyword': ka.keyword,
        'page_url': ka.page_url,
        'page_title': ka.page_title or '',
        'page_type': ka.page_type or '',
        'silo_name': silo_name,
        'gsc_impressions': ka.gsc_impressions or 0,
        'gsc_clicks': ka.gsc_clicks or 0,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/keywords/validate
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_validate(request):
    """Check keyword availability — exact match → block, substring → warn, else pass."""
    site, err = _get_site_or_error(request)
    if err:
        return err

    keyword = (request.data.get('keyword') or '').strip().lower()
    if not keyword:
        return Response(
            {'error': {'code': 'BAD_REQUEST', 'message': 'keyword is required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    assignments = KeywordAssignment.objects.filter(site=site, status='active').select_related('silo')

    # Exact match → BLOCK
    for ka in assignments:
        if ka.keyword.lower() == keyword:
            msg = f'This keyword is already assigned to "{ka.page_title}" ({ka.page_url}).'
            return Response({
                'status': 'block',
                'keyword': keyword,
                'message': msg,
                'matches': [_build_match(ka, 'exact')],
            })

    # Substring / overlap → WARN
    matches = []
    for ka in assignments:
        kw = ka.keyword.lower()
        if keyword in kw or kw in keyword:
            matches.append(_build_match(ka, 'substring'))

    if matches:
        first = matches[0]
        msg = f'Similar keyword found: "{first["keyword"]}" is assigned to {first["page_url"]}.'
        return Response({
            'status': 'warn',
            'keyword': keyword,
            'message': msg,
            'matches': matches,
        })

    return Response({
        'status': 'pass',
        'keyword': keyword,
        'message': None,
        'matches': [],
    })


# ---------------------------------------------------------------------------
# POST /api/v1/keywords/assign
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_assign(request):
    """Register a keyword to a URL."""
    site, err = _get_site_or_error(request)
    if err:
        return err

    keyword = (request.data.get('keyword') or '').strip()
    page_url = request.data.get('page_url', '')
    page_id = request.data.get('page_id')
    page_title = request.data.get('page_title', '')
    page_type = request.data.get('page_type', 'spoke')
    silo_id = request.data.get('silo_id')
    assignment_source = request.data.get('assignment_source', 'manual')

    if not keyword or not page_url:
        return Response(
            {'error': {'code': 'BAD_REQUEST', 'message': 'keyword and page_url are required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Check for existing assignment
    existing = KeywordAssignment.objects.filter(site=site, keyword=keyword.lower(), status='active').first()
    if existing:
        return Response(
            {
                'error': {
                    'code': 'KEYWORD_ALREADY_ASSIGNED',
                    'message': 'This keyword is already assigned to another page.',
                    'detail': {
                        'keyword': existing.keyword,
                        'existing_url': existing.page_url,
                    },
                    'status': 409,
                }
            },
            status=status.HTTP_409_CONFLICT,
        )

    try:
        ka = KeywordAssignment.objects.create(
            site=site,
            keyword=keyword.lower(),
            page_url=page_url,
            page_id=page_id,
            page_title=page_title,
            page_type=page_type,
            silo_id=silo_id,
            assignment_source=assignment_source,
            status='active',
        )
    except IntegrityError:
        return Response(
            {
                'error': {
                    'code': 'KEYWORD_ALREADY_ASSIGNED',
                    'message': 'This keyword is already assigned to another page.',
                    'detail': {'keyword': keyword},
                    'status': 409,
                }
            },
            status=status.HTTP_409_CONFLICT,
        )

    # Audit trail
    KeywordAssignmentHistory.objects.create(
        assignment=ka,
        site=site,
        keyword=ka.keyword,
        new_url=ka.page_url,
        new_page_type=ka.page_type,
        action='assign',
        performed_by=str(request.user),
    )

    return Response({
        'id': str(ka.id),
        'keyword': ka.keyword,
        'page_url': ka.page_url,
        'page_title': ka.page_title,
        'page_type': ka.page_type,
        'status': ka.status,
        'assigned_at': ka.assigned_at.isoformat(),
    }, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# PUT /api/v1/keywords/{id}/reassign
# ---------------------------------------------------------------------------

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def keyword_reassign(request, pk):
    """Reassign keyword ownership from one page to another with audit trail."""
    ka = get_object_or_404(KeywordAssignment, pk=pk, status='active')

    # Permission check via site
    site = ka.site
    if site.user != request.user:
        return Response(
            {'error': {'code': 'FORBIDDEN', 'message': 'Permission denied.', 'status': 403}},
            status=status.HTTP_403_FORBIDDEN,
        )

    new_page_url = request.data.get('new_page_url', '')
    new_page_id = request.data.get('new_page_id')
    new_page_title = request.data.get('new_page_title', '')
    new_page_type = request.data.get('new_page_type', ka.page_type)
    new_silo_id = request.data.get('new_silo_id', str(ka.silo_id) if ka.silo_id else None)
    reason = request.data.get('reason', '')
    performed_by = request.data.get('performed_by', str(request.user))

    if not new_page_url:
        return Response(
            {'error': {'code': 'BAD_REQUEST', 'message': 'new_page_url is required.', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Save old values for audit
    old_url = ka.page_url
    old_page_type = ka.page_type

    # Update the assignment
    ka.page_url = new_page_url
    ka.page_id = new_page_id
    ka.page_title = new_page_title
    ka.page_type = new_page_type
    if new_silo_id:
        ka.silo_id = new_silo_id
    ka.save()

    # Create audit history
    KeywordAssignmentHistory.objects.create(
        assignment=ka,
        site=site,
        keyword=ka.keyword,
        previous_url=old_url,
        new_url=new_page_url,
        previous_page_type=old_page_type,
        new_page_type=new_page_type,
        action='reassign',
        reason=reason,
        performed_by=performed_by,
    )

    return Response({
        'id': str(ka.id),
        'keyword': ka.keyword,
        'page_url': ka.page_url,
        'page_title': ka.page_title,
        'page_type': ka.page_type,
        'previous_url': old_url,
        'status': ka.status,
        'reassigned_at': ka.updated_at.isoformat(),
    })


# ---------------------------------------------------------------------------
# GET /api/v1/keywords
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def keyword_list(request):
    """List keyword assignments with filtering and pagination."""
    site, err = _get_site_or_error(request)
    if err:
        return err

    qs = KeywordAssignment.objects.filter(site=site).select_related('silo').order_by('-assigned_at')

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    silo_id = request.query_params.get('silo_id')
    if silo_id:
        qs = qs.filter(silo_id=silo_id)

    page_type = request.query_params.get('page_type')
    if page_type:
        qs = qs.filter(page_type=page_type)

    search = request.query_params.get('search', '').strip()
    if search:
        # Trigram / icontains search on keyword, page_title, page_url
        qs = qs.filter(
            Q(keyword__icontains=search) |
            Q(page_title__icontains=search) |
            Q(page_url__icontains=search)
        )

    # Pagination
    total = qs.count()
    try:
        page_num = max(int(request.query_params.get('page', 1)), 1)
    except (ValueError, TypeError):
        page_num = 1
    try:
        per_page = min(max(int(request.query_params.get('per_page', 25)), 1), 100)
    except (ValueError, TypeError):
        per_page = 25

    total_pages = max(math.ceil(total / per_page), 1)
    offset = (page_num - 1) * per_page
    items = qs[offset:offset + per_page]

    data = []
    for ka in items:
        silo_name = ''
        if ka.silo:
            silo_name = ka.silo.name
        data.append({
            'id': str(ka.id),
            'keyword': ka.keyword,
            'page_url': ka.page_url,
            'page_id': ka.page_id,
            'page_title': ka.page_title or '',
            'page_type': ka.page_type,
            'silo_id': str(ka.silo_id) if ka.silo_id else None,
            'silo_name': silo_name,
            'assignment_source': ka.assignment_source,
            'status': ka.status,
            'gsc_impressions': ka.gsc_impressions,
            'gsc_clicks': ka.gsc_clicks,
            'assigned_at': ka.assigned_at.isoformat(),
            'updated_at': ka.updated_at.isoformat(),
        })

    return Response({
        'data': data,
        'meta': {
            'total': total,
            'page': page_num,
            'per_page': per_page,
            'total_pages': total_pages,
        },
    })


# ---------------------------------------------------------------------------
# POST /api/v1/keywords/bootstrap
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_bootstrap(request):
    """Bootstrap keyword registry from existing pages."""
    site, err = _get_site_or_error(request)
    if err:
        return err

    from seo.models import Page
    estimated = Page.objects.filter(site=site, status='publish', is_noindex=False).count()

    # For now run synchronously; return async-style response
    result = bootstrap_keyword_registry(site)

    return Response({
        'status': 'completed',
        'job_id': str(uuid.uuid4()),
        'estimated_pages': estimated,
        'message': 'Bootstrapping keyword registry. This may take 2-5 minutes.',
        'result': {
            'total_pages': result.get('total_pages', 0),
            'keywords_assigned': result.get('keywords_assigned', 0),
            'conflicts_found': result.get('conflicts_found', 0),
        },
    })


# ---------------------------------------------------------------------------
# LEGACY endpoints (keep for backward compat with old URL patterns)
# ---------------------------------------------------------------------------

def _get_site_or_403(request, site_id):
    site = get_object_or_404(Site, id=site_id)
    if site.user != request.user:
        return None, Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    return site, None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def keyword_registry_list(request, site_id):
    """GET /api/v1/sites/{site_id}/keyword-registry/ (LEGACY)"""
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    qs = KeywordAssignment.objects.filter(site=site).select_related('silo')
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)
    page_type = request.query_params.get('page_type')
    if page_type:
        qs = qs.filter(page_type=page_type)
    data = [
        {
            'id': str(ka.id),
            'keyword': ka.keyword,
            'page_url': ka.page_url,
            'page_id': ka.page_id,
            'page_title': ka.page_title,
            'silo_id': str(ka.silo_id) if ka.silo_id else None,
            'page_type': ka.page_type,
            'assignment_source': ka.assignment_source,
            'status': ka.status,
            'assigned_at': ka.assigned_at.isoformat() if ka.assigned_at else None,
            'updated_at': ka.updated_at.isoformat() if ka.updated_at else None,
        }
        for ka in qs
    ]
    return Response({'keyword_assignments': data, 'total': len(data)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_registry_bootstrap(request, site_id):
    """POST /api/v1/sites/{site_id}/keyword-registry/bootstrap/ (LEGACY)"""
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    result = bootstrap_keyword_registry(site)
    return Response(result, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_registry_check(request, site_id):
    """POST /api/v1/sites/{site_id}/keyword-registry/check/ (LEGACY)"""
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    keyword = request.data.get('keyword', '').strip()
    if not keyword:
        return Response({'error': 'keyword is required'}, status=status.HTTP_400_BAD_REQUEST)
    available = check_keyword_available(site, keyword)
    resp = {'keyword': keyword, 'available': available}
    if not available:
        owner = get_keyword_owner(site, keyword)
        if owner:
            resp['owner'] = {
                'page_url': owner.page_url,
                'page_title': owner.page_title,
            }
    return Response(resp)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_registry_assign(request, site_id):
    """POST /api/v1/sites/{site_id}/keyword-registry/assign/ (LEGACY)"""
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    keyword = request.data.get('keyword', '').strip()
    page_url = request.data.get('page_url', '')
    page_id = request.data.get('page_id')
    page_title = request.data.get('page_title', '')
    page_type = request.data.get('page_type', 'general')
    silo_id = request.data.get('silo_id')
    if not keyword or not page_url:
        return Response({'error': 'keyword and page_url are required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        ka = KeywordAssignment.objects.create(
            site=site, keyword=keyword.lower(), page_url=page_url,
            page_id=page_id, page_title=page_title, page_type=page_type,
            silo_id=silo_id, assignment_source='manual', status='active',
        )
    except IntegrityError:
        owner = get_keyword_owner(site, keyword)
        conflict = {}
        if owner:
            conflict = {'page_url': owner.page_url, 'page_title': owner.page_title}
        return Response(
            {'error': f'Keyword "{keyword}" is already assigned on this site.', 'conflict': conflict},
            status=status.HTTP_409_CONFLICT,
        )
    return Response({'id': str(ka.id), 'keyword': ka.keyword, 'page_url': ka.page_url, 'status': ka.status},
                    status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def keyword_registry_reassign(request, site_id):
    """POST /api/v1/sites/{site_id}/keyword-registry/reassign/ (LEGACY)"""
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    keyword = request.data.get('keyword', '').strip()
    new_page_url = request.data.get('new_page_url', '')
    reason = request.data.get('reason', '')
    if not keyword or not new_page_url:
        return Response({'error': 'keyword and new_page_url are required'}, status=status.HTTP_400_BAD_REQUEST)
    ka = KeywordAssignment.objects.filter(site=site, keyword=keyword.lower(), status='active').first()
    if not ka:
        return Response({'error': f'No active assignment for "{keyword}".'}, status=status.HTTP_404_NOT_FOUND)
    old_url = ka.page_url
    ka.page_url = new_page_url
    ka.page_id = request.data.get('new_page_id')
    ka.page_title = request.data.get('new_page_title', ka.page_title)
    ka.save()
    KeywordAssignmentHistory.objects.create(
        assignment=ka, site=site, keyword=ka.keyword,
        previous_url=old_url, new_url=new_page_url,
        action='reassign', reason=reason, performed_by=str(request.user),
    )
    return Response({'id': str(ka.id), 'keyword': ka.keyword, 'page_url': ka.page_url, 'status': ka.status})
