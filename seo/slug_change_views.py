"""
API endpoints for Slug Change Engine with Auto-Redirect.
When a page's slug needs to change (for SEO or conflict resolution),
automatically create a 301 redirect from old slug to new slug.

Safety: Always create redirect BEFORE changing slug. If redirect creation fails, abort slug change.
"""
import logging
from urllib.parse import urlparse, urljoin

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import Page, RedirectRegistry, SlugChangeLog
from integrations.wordpress_webhook import send_webhook_to_wordpress

logger = logging.getLogger(__name__)


def _get_site_or_403(request, site_id=None):
    """Helper to get site and check ownership."""
    if site_id is None:
        site_id = request.data.get('site_id')
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


def _serialize_slug_change(change):
    """Serialize a SlugChangeLog object."""
    return {
        'id': str(change.id),
        'page_id': change.page_id,
        'old_url': change.old_url,
        'old_slug': change.old_slug,
        'new_url': change.new_url,
        'new_slug': change.new_slug,
        'redirect_id': str(change.redirect.id) if change.redirect else None,
        'redirect_status': change.redirect_status,
        'slug_change_status': change.slug_change_status,
        'reason': change.reason,
        'error_message': change.error_message,
        'changed_by': change.changed_by,
        'changed_at': change.changed_at.isoformat(),
        'updated_at': change.updated_at.isoformat(),
    }


def _build_new_url(old_url, new_slug):
    """Build new URL by replacing the slug in the old URL."""
    parsed = urlparse(old_url)
    path_parts = parsed.path.rstrip('/').split('/')
    if path_parts:
        path_parts[-1] = new_slug
    new_path = '/'.join(path_parts) + '/'
    return f"{parsed.scheme}://{parsed.netloc}{new_path}"


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_slug(request, site_id, page_id):
    """
    POST /api/v1/sites/{site_id}/pages/{page_id}/change-slug/
    
    Change a page's slug with automatic 301 redirect creation.
    
    Body:
        {
            "new_slug": "new-slug-here",
            "reason": "seo_optimization",  // optional
            "changed_by": "user@example.com"  // optional
        }
    
    Process:
        1. Validate the new slug
        2. Create 301 redirect from old URL to new URL
        3. Send webhook to WordPress to change slug
        4. Track in slug_change_log
    
    Safety: If redirect creation fails, abort the slug change.
    """
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    
    # Get the page
    try:
        page = Page.objects.get(site=site, wp_post_id=page_id)
    except Page.DoesNotExist:
        return Response(
            {'error': {'code': 'PAGE_NOT_FOUND', 'message': f'Page {page_id} not found', 'status': 404}},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Get request data
    new_slug = request.data.get('new_slug', '').strip()
    reason = request.data.get('reason', 'seo_optimization')
    changed_by = request.data.get('changed_by', 'siloq_system')
    
    if not new_slug:
        return Response(
            {'error': {'code': 'INVALID_INPUT', 'message': 'new_slug is required', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Validate slug format (basic check)
    if not new_slug.replace('-', '').replace('_', '').isalnum():
        return Response(
            {'error': {'code': 'INVALID_SLUG', 'message': 'Slug must contain only letters, numbers, hyphens, and underscores', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Check if slug is different
    if page.slug == new_slug:
        return Response(
            {'error': {'code': 'NO_CHANGE', 'message': 'New slug is the same as current slug', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    old_url = page.url
    old_slug = page.slug
    new_url = _build_new_url(old_url, new_slug)
    
    # Check if redirect already exists from this source
    existing_redirect = RedirectRegistry.objects.filter(
        site=site,
        source_url=old_url,
        status='active'
    ).first()
    
    if existing_redirect:
        return Response(
            {'error': {'code': 'REDIRECT_EXISTS', 'message': f'A redirect from {old_url} already exists', 'status': 409}},
            status=status.HTTP_409_CONFLICT,
        )
    
    # Use transaction to ensure atomicity
    try:
        with transaction.atomic():
            # Step 1: Create redirect FIRST (safety requirement)
            redirect = RedirectRegistry.objects.create(
                site=site,
                source_url=old_url,
                target_url=new_url,
                redirect_type=301,
                reason='slug_change',
                created_by=changed_by,
                status='active',
            )
            
            # Step 2: Create slug change log
            slug_change = SlugChangeLog.objects.create(
                site=site,
                page_id=page_id,
                old_url=old_url,
                old_slug=old_slug,
                new_url=new_url,
                new_slug=new_slug,
                redirect=redirect,
                redirect_status='created',
                slug_change_status='pending',
                reason=reason,
                changed_by=changed_by,
            )
            
            # Step 3: Send webhook to WordPress to change slug
            webhook_data = {
                'event_type': 'page.change_slug',
                'page_id': page_id,
                'old_slug': old_slug,
                'new_slug': new_slug,
                'old_url': old_url,
                'new_url': new_url,
                'redirect_id': str(redirect.id),
            }
            
            webhook_response = send_webhook_to_wordpress(site, webhook_data)
            
            if not webhook_response or webhook_response.get('status') != 'success':
                # Webhook failed - mark as failed but keep redirect
                slug_change.slug_change_status = 'failed'
                slug_change.error_message = webhook_response.get('message', 'Webhook failed') if webhook_response else 'No response from WordPress'
                slug_change.save()
                
                logger.error(f"[Slug Change] Webhook failed for page {page_id}: {slug_change.error_message}")
                
                return Response(
                    {
                        'success': False,
                        'message': 'Redirect created but slug change failed on WordPress',
                        'error': slug_change.error_message,
                        'slug_change': _serialize_slug_change(slug_change),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            
            # Success - update slug change status
            slug_change.slug_change_status = 'completed'
            slug_change.save()
            
            # Update page record
            page.slug = new_slug
            page.url = new_url
            page.save()
            
            logger.info(f"[Slug Change] Successfully changed slug for page {page_id}: {old_slug} → {new_slug}")
            
            return Response({
                'success': True,
                'message': 'Slug changed successfully with automatic redirect',
                'slug_change': _serialize_slug_change(slug_change),
            }, status=status.HTTP_200_OK)
            
    except Exception as e:
        logger.exception(f"[Slug Change] Error changing slug for page {page_id}")
        return Response(
            {'error': {'code': 'INTERNAL_ERROR', 'message': str(e), 'status': 500}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_change_slugs(request, site_id):
    """
    POST /api/v1/sites/{site_id}/pages/bulk-change-slugs/
    
    Batch change slugs for silo reorganization.
    
    Body:
        {
            "changes": [
                {
                    "page_id": 123,
                    "new_slug": "new-slug-1"
                },
                {
                    "page_id": 456,
                    "new_slug": "new-slug-2"
                }
            ],
            "reason": "silo_reorganization",  // optional
            "changed_by": "user@example.com"  // optional
        }
    
    Returns:
        {
            "success": true,
            "total": 2,
            "succeeded": 2,
            "failed": 0,
            "results": [...]
        }
    """
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    
    changes = request.data.get('changes', [])
    reason = request.data.get('reason', 'silo_reorganization')
    changed_by = request.data.get('changed_by', 'siloq_system')
    
    if not changes or not isinstance(changes, list):
        return Response(
            {'error': {'code': 'INVALID_INPUT', 'message': 'changes array is required', 'status': 400}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    results = []
    succeeded = 0
    failed = 0
    
    for change_data in changes:
        page_id = change_data.get('page_id')
        new_slug = change_data.get('new_slug')
        
        if not page_id or not new_slug:
            results.append({
                'page_id': page_id,
                'success': False,
                'error': 'Missing page_id or new_slug',
            })
            failed += 1
            continue
        
        # Call single change_slug logic
        try:
            page = Page.objects.get(site=site, wp_post_id=page_id)
            old_url = page.url
            old_slug = page.slug
            new_url = _build_new_url(old_url, new_slug)
            
            # Check for existing redirect
            existing_redirect = RedirectRegistry.objects.filter(
                site=site,
                source_url=old_url,
                status='active'
            ).first()
            
            if existing_redirect:
                results.append({
                    'page_id': page_id,
                    'success': False,
                    'error': f'Redirect from {old_url} already exists',
                })
                failed += 1
                continue
            
            with transaction.atomic():
                # Create redirect
                redirect = RedirectRegistry.objects.create(
                    site=site,
                    source_url=old_url,
                    target_url=new_url,
                    redirect_type=301,
                    reason='slug_change',
                    created_by=changed_by,
                    status='active',
                )
                
                # Create log
                slug_change = SlugChangeLog.objects.create(
                    site=site,
                    page_id=page_id,
                    old_url=old_url,
                    old_slug=old_slug,
                    new_url=new_url,
                    new_slug=new_slug,
                    redirect=redirect,
                    redirect_status='created',
                    slug_change_status='pending',
                    reason=reason,
                    changed_by=changed_by,
                )
                
                # Send webhook
                webhook_data = {
                    'event_type': 'page.change_slug',
                    'page_id': page_id,
                    'old_slug': old_slug,
                    'new_slug': new_slug,
                    'old_url': old_url,
                    'new_url': new_url,
                    'redirect_id': str(redirect.id),
                }
                
                webhook_response = send_webhook_to_wordpress(site, webhook_data)
                
                if not webhook_response or webhook_response.get('status') != 'success':
                    slug_change.slug_change_status = 'failed'
                    slug_change.error_message = webhook_response.get('message', 'Webhook failed') if webhook_response else 'No response'
                    slug_change.save()
                    
                    results.append({
                        'page_id': page_id,
                        'success': False,
                        'error': slug_change.error_message,
                    })
                    failed += 1
                else:
                    slug_change.slug_change_status = 'completed'
                    slug_change.save()
                    
                    page.slug = new_slug
                    page.url = new_url
                    page.save()
                    
                    results.append({
                        'page_id': page_id,
                        'success': True,
                        'old_slug': old_slug,
                        'new_slug': new_slug,
                        'redirect_id': str(redirect.id),
                    })
                    succeeded += 1
                    
        except Page.DoesNotExist:
            results.append({
                'page_id': page_id,
                'success': False,
                'error': f'Page {page_id} not found',
            })
            failed += 1
        except Exception as e:
            logger.exception(f"[Bulk Slug Change] Error for page {page_id}")
            results.append({
                'page_id': page_id,
                'success': False,
                'error': str(e),
            })
            failed += 1
    
    return Response({
        'success': True,
        'total': len(changes),
        'succeeded': succeeded,
        'failed': failed,
        'results': results,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_slug_changes(request, site_id):
    """
    GET /api/v1/sites/{site_id}/slug-changes/
    
    List all slug changes with redirect status.
    
    Query params:
        - page: Page number (default: 1)
        - per_page: Items per page (default: 50)
        - status: Filter by slug_change_status
        - page_id: Filter by page_id
    """
    site, err = _get_site_or_403(request, site_id)
    if err:
        return err
    
    qs = SlugChangeLog.objects.filter(site=site)
    
    # Filters
    slug_status = request.query_params.get('status')
    if slug_status:
        qs = qs.filter(slug_change_status=slug_status)
    
    page_id_filter = request.query_params.get('page_id')
    if page_id_filter:
        try:
            qs = qs.filter(page_id=int(page_id_filter))
        except ValueError:
            pass
    
    # Pagination
    page = int(request.query_params.get('page', 1))
    per_page = int(request.query_params.get('per_page', 50))
    total = qs.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page
    items = qs.select_related('redirect').order_by('-changed_at')[offset:offset + per_page]
    
    return Response({
        'success': True,
        'slug_changes': [_serialize_slug_change(sc) for sc in items],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
        },
    }, status=status.HTTP_200_OK)
