"""
API endpoints for Redirect Management (Section 6).
"""
import logging
import uuid
from datetime import timezone

import requests as http_requests
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import RedirectRegistry, Page, CannibalizationConflict
from integrations.wordpress_webhook import send_webhook_to_wordpress

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


def _serialize_redirect(r):
    return {
        'id': str(r.id),
        'source_url': r.source_url,
        'target_url': r.target_url,
        'redirect_type': r.redirect_type,
        'reason': r.reason,
        'status': r.status,
        'is_verified': r.is_verified,
        'last_verified': r.last_verified.isoformat() if r.last_verified else None,
        'verification_status': r.verification_status,
        'chain_depth': r.chain_depth,
        'final_destination': r.final_destination,
        'total_hits': r.total_hits,
        'created_by': r.created_by,
        'created_at': r.created_at.isoformat(),
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def redirect_list_create(request):
    """
    GET  /api/v1/redirects?site_id=...  — List redirects with filters.
    POST /api/v1/redirects              — Create redirect with chain/loop detection.
    """
    if request.method == 'GET':
        return _list_redirects(request)
    return _create_redirect(request)


def _list_redirects(request):
    site, err = _get_site_or_403(request)
    if err:
        return err

    qs = RedirectRegistry.objects.filter(site=site)

    # Filters
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)
    reason = request.query_params.get('reason')
    if reason:
        qs = qs.filter(reason=reason)

    # Pagination
    page = int(request.query_params.get('page', 1))
    per_page = int(request.query_params.get('per_page', 50))
    total = qs.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page
    items = qs.order_by('-created_at')[offset:offset + per_page]

    # Meta counts
    counts = RedirectRegistry.objects.filter(site=site).aggregate(
        active=Count('id', filter=Q(status='active')),
        broken=Count('id', filter=Q(verification_status='broken')),
        chains=Count('id', filter=Q(chain_depth__gt=0)),
    )

    return Response({
        'data': [_serialize_redirect(r) for r in items],
        'meta': {
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'active_count': counts['active'],
            'broken_count': counts['broken'],
            'chain_count': counts['chains'],
        },
    })


def _create_redirect(request):
    site, err = _get_site_or_403(request)
    if err:
        return err

    source_url = request.data.get('source_url')
    target_url = request.data.get('target_url')
    redirect_type = request.data.get('redirect_type', 301)
    reason = request.data.get('reason', 'manual')

    if not source_url or not target_url:
        return Response(
            {'error': {'code': 'VALIDATION_ERROR', 'message': 'source_url and target_url are required', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Loop detection: does target_url → source_url exist?
    loop = RedirectRegistry.objects.filter(
        site=site, source_url=target_url, target_url=source_url, status='active',
    ).exists()
    if loop:
        return Response(
            {'error': {
                'code': 'REDIRECT_LOOP',
                'message': f'Creating {source_url} → {target_url} would create a redirect loop.',
                'detail': {'source_url': source_url, 'target_url': target_url},
                'status': 422,
            }},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Chain detection: does target_url → somewhere else exist?
    chain_warning = None
    chain_redirect = RedirectRegistry.objects.filter(
        site=site, source_url=target_url, status='active',
    ).first()
    if chain_redirect:
        chain_warning = {
            'chain_detected': True,
            'message': f'{target_url} already redirects to {chain_redirect.target_url}. Consider redirecting directly to {chain_redirect.target_url}.',
            'suggestion': {
                'source_url': source_url,
                'target_url': chain_redirect.target_url,
            },
        }

    redirect = RedirectRegistry.objects.create(
        site=site,
        source_url=source_url,
        target_url=target_url,
        redirect_type=redirect_type,
        reason=reason,
        status='active',
        chain_depth=1 if chain_redirect else 0,
        final_destination=chain_redirect.target_url if chain_redirect else target_url,
        created_by=request.data.get('created_by', 'siloq_system'),
    )

    response_data = {'data': _serialize_redirect(redirect)}
    if chain_warning:
        response_data['chain_warning'] = chain_warning

    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def redirect_verify(request):
    """POST /api/v1/redirects/verify — Verify all redirects for a site."""
    site, err = _get_site_or_403(request)
    if err:
        return err

    redirects = RedirectRegistry.objects.filter(site=site, status='active')
    issues = []
    healthy = 0
    broken = 0
    chains = 0
    loops = 0
    now = dj_timezone.now()

    for r in redirects:
        issue_list = []

        # Check if target returns 200
        try:
            resp = http_requests.head(r.target_url, timeout=10, allow_redirects=False)
            if resp.status_code >= 400:
                issue_list.append({
                    'type': 'broken',
                    'message': f'Target returned HTTP {resp.status_code}',
                })
                broken += 1
        except Exception:
            issue_list.append({'type': 'broken', 'message': 'Target URL unreachable'})
            broken += 1

        # Chain detection
        chain = RedirectRegistry.objects.filter(
            site=site, source_url=r.target_url, status='active',
        ).first()
        if chain:
            issue_list.append({
                'type': 'chain',
                'message': f'Chain: {r.source_url} → {r.target_url} → {chain.target_url}',
                'final_destination': chain.target_url,
            })
            chains += 1

        # Loop detection
        loop = RedirectRegistry.objects.filter(
            site=site, source_url=r.target_url, target_url=r.source_url, status='active',
        ).exists()
        if loop:
            issue_list.append({
                'type': 'loop',
                'message': f'Loop: {r.source_url} ↔ {r.target_url}',
            })
            loops += 1

        # Update verification
        v_status = 'broken' if any(i['type'] == 'broken' for i in issue_list) else 'healthy'
        r.is_verified = True
        r.last_verified = now
        r.verification_status = v_status
        r.save(update_fields=['is_verified', 'last_verified', 'verification_status'])

        if issue_list:
            issues.append({
                'redirect_id': str(r.id),
                'source_url': r.source_url,
                'target_url': r.target_url,
                'issues': issue_list,
            })
        else:
            healthy += 1

    return Response({
        'summary': {
            'total_checked': redirects.count(),
            'healthy': healthy,
            'broken': broken,
            'chains': chains,
            'loops': loops,
        },
        'issues': issues,
    })


# ===================================================================
# Site-scoped endpoints for cannibalization redirect resolution
# ===================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_redirect(request, site_id):
    """
    Create a 301 redirect and push to WordPress.
    
    URL: POST /api/v1/sites/{site_id}/redirects/create/
    
    Body:
    - from_url: str (the losing URL path, e.g., "/overland-park-ks-tile-installation/")
    - to_url: str (the winning URL path, e.g., "/service-area/overland-park-ks/")
    - reason: str (optional, e.g., "Cannibalization resolution")
    - conflict_keyword: str (optional, for tracking)
    """
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)
    
    from_url = request.data.get('from_url')
    to_url = request.data.get('to_url')
    reason = request.data.get('reason', 'Cannibalization resolution')
    conflict_keyword = request.data.get('conflict_keyword', '')
    
    if not from_url or not to_url:
        return Response(
            {'error': 'Both from_url and to_url are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Normalize URLs (ensure they start with /)
    if not from_url.startswith('/'):
        from_url = '/' + from_url
    if not to_url.startswith('/'):
        to_url = '/' + to_url
    
    # Validate URLs belong to site
    site_base = site.url.rstrip('/')
    from_full = site_base + from_url
    to_full = site_base + to_url
    
    from_page = Page.objects.filter(site=site, url=from_full).first()
    to_page = Page.objects.filter(site=site, url=to_full).first()
    
    if not from_page:
        logger.warning(f"Source URL {from_full} not found in pages for site {site.name}")
    
    if not to_page:
        logger.warning(f"Target URL {to_full} not found in pages for site {site.name}")
    
    # Check for existing redirect
    existing = RedirectRegistry.objects.filter(
        site=site,
        source_url=from_url,
        status='active'
    ).first()
    
    if existing:
        return Response(
            {'error': f'Active redirect already exists from {from_url}'},
            status=status.HTTP_409_CONFLICT
        )
    
    # Try to link to conflict if keyword provided
    conflict = None
    if conflict_keyword:
        conflict = CannibalizationConflict.objects.filter(
            site=site,
            keyword=conflict_keyword
        ).order_by('-detected_at').first()
    
    # Create redirect record
    redirect = RedirectRegistry.objects.create(
        site=site,
        source_url=from_url,
        target_url=to_url,
        redirect_type=301,
        reason=reason,
        conflict=conflict,
        status='active',
        created_by=request.user.email if hasattr(request.user, 'email') else 'siloq_user'
    )
    
    # Send webhook to WordPress
    webhook_payload = {
        'from_url': from_url,
        'to_url': to_url,
        'type': 301
    }
    
    webhook_result = send_webhook_to_wordpress(site, 'redirect.create', webhook_payload)
    
    if not webhook_result['success']:
        logger.error(
            f"Failed to push redirect to WordPress for site {site.name}: {webhook_result['error']}"
        )
        # Don't fail the request, but log it
        redirect.status = 'pending'
        redirect.save()
    
    # Mark the losing page as redirected
    if from_page:
        from_page.status = 'redirected'
        from_page.save()
        logger.info(f"Marked page {from_page.id} ({from_url}) as redirected")
    
    return Response({
        'success': True,
        'redirect': {
            'id': str(redirect.id),
            'from_url': redirect.source_url,
            'to_url': redirect.target_url,
            'type': redirect.redirect_type,
            'reason': redirect.reason,
            'status': redirect.status,
            'created_at': redirect.created_at.isoformat(),
        },
        'webhook_pushed': webhook_result['success'],
        'webhook_status': webhook_result.get('status_code'),
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_redirects(request, site_id):
    """
    List all redirects for a site from redirect_registry.
    
    URL: GET /api/v1/sites/{site_id}/redirects/
    
    Query params:
    - status: filter by status (active, removed, etc.)
    - limit: number of results (default 100)
    """
    try:
        site = Site.objects.get(id=site_id)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)
    
    redirects_qs = RedirectRegistry.objects.filter(site=site)
    
    # Filter by status if provided
    status_filter = request.query_params.get('status')
    if status_filter:
        redirects_qs = redirects_qs.filter(status=status_filter)
    
    # Limit results
    limit = int(request.query_params.get('limit', 100))
    redirects_qs = redirects_qs.order_by('-created_at')[:limit]
    
    redirects_data = [
        {
            'id': str(r.id),
            'from_url': r.source_url,
            'to_url': r.target_url,
            'type': r.redirect_type,
            'reason': r.reason,
            'status': r.status,
            'conflict_keyword': r.conflict.keyword if r.conflict else None,
            'created_by': r.created_by,
            'created_at': r.created_at.isoformat(),
            'is_verified': r.is_verified,
            'last_verified': r.last_verified.isoformat() if r.last_verified else None,
        }
        for r in redirects_qs
    ]
    
    return Response({
        'site_id': site_id,
        'redirects': redirects_data,
        'count': len(redirects_data),
    }, status=status.HTTP_200_OK)
