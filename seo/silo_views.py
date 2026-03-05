"""
API endpoints for Silo Management (Section 10).
"""
import logging
from collections import defaultdict

from django.core.cache import cache
from django.db.models import Count, Avg, Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import (
    Page,
    InternalLink,
    SiloDefinition,
    KeywordAssignment,
    CannibalizationConflict,
    ContentHealthScore,
    PageAnalysis,
)

logger = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    return (url or '').rstrip('/').lower()


def _serialize_page(page, gsc_metrics, include_linked_to_pillar=None):
    page_data = {
        'id': page.id,
        'title': page.title,
        'url': page.url,
        'impressions': int(gsc_metrics.get('impressions', 0) or 0),
        'clicks': int(gsc_metrics.get('clicks', 0) or 0),
        'position': float(gsc_metrics.get('position', 0) or 0),
        'internal_links_in': int(getattr(page, 'internal_links_in', 0) or 0),
        'internal_links_out': int(getattr(page, 'internal_links_out', 0) or 0),
    }
    if include_linked_to_pillar is not None:
        page_data['linked_to_pillar'] = bool(include_linked_to_pillar)
    return page_data


def _get_site_or_403(request):
    site_id = request.query_params.get('site_id')
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def silo_list(request):
    """GET /api/v1/silos — List silos with aggregated stats."""
    site, err = _get_site_or_403(request)
    if err:
        return err

    silos = SiloDefinition.objects.filter(site=site).annotate(
        keyword_count=Count('keyword_assignments', distinct=True),
        spoke_count=Count(
            'keyword_assignments',
            filter=Q(keyword_assignments__page_type='spoke'),
            distinct=True,
        ),
    ).order_by('name')

    data = []
    for silo in silos:
        # Open conflicts: conflicts where at least one ConflictPage URL
        # matches a KeywordAssignment in this silo
        silo_page_urls = KeywordAssignment.objects.filter(
            silo=silo, status='active',
        ).values_list('page_url', flat=True)

        conflicts_open = CannibalizationConflict.objects.filter(
            site=site,
            status='open',
            pages__page_url__in=silo_page_urls,
        ).distinct().count()

        # Avg health score for pages in this silo
        avg_health = ContentHealthScore.objects.filter(
            site=site,
            page_url__in=silo_page_urls,
        ).aggregate(avg=Avg('health_score'))['avg']

        data.append({
            'id': str(silo.id),
            'name': silo.name,
            'slug': silo.slug,
            'hub_page_url': silo.hub_page_url,
            'status': silo.status,
            'description': silo.description,
            'keyword_count': silo.keyword_count,
            'spoke_count': silo.spoke_count,
            'conflicts_open': conflicts_open,
            'avg_health_score': round(avg_health, 1) if avg_health is not None else None,
            'created_at': silo.created_at.isoformat(),
        })

    return Response({
        'data': data,
        'meta': {
            'total': len(data),
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def silo_map(request, site_id: int):
    """
    GET /api/v1/sites/{site_id}/silo-map/

    Returns silo structure with pillar/supporting pages and internal-link coverage.
    """
    site = get_object_or_404(Site, id=site_id, user=request.user)

    cache_key = f"silo-map:v1:user:{request.user.id}:site:{site.id}"
    cached_payload = cache.get(cache_key)
    if cached_payload:
        return Response(cached_payload)

    all_pages = list(
        Page.objects
        .filter(site=site)
        .annotate(
            internal_links_in=Count(
                'incoming_links',
                filter=Q(incoming_links__site=site, incoming_links__is_valid=True),
                distinct=True,
            ),
            internal_links_out=Count(
                'outgoing_links',
                filter=Q(outgoing_links__site=site, outgoing_links__is_valid=True),
                distinct=True,
            ),
        )
    )

    page_by_id = {p.id: p for p in all_pages}
    page_by_url = {_normalize_url(p.url): p for p in all_pages if p.url}

    gsc_metrics_by_page_id = {}
    gsc_metrics_by_url = {}
    analyses = PageAnalysis.objects.filter(site=site).order_by('-created_at').values('page_url', 'gsc_data')
    for row in analyses:
        page_url = _normalize_url(row.get('page_url') or '')
        if not page_url or page_url in gsc_metrics_by_url:
            continue

        gsc_data = row.get('gsc_data') or {}
        if not isinstance(gsc_data, dict):
            gsc_data = {}

        metrics = {
            'impressions': gsc_data.get('impressions') or gsc_data.get('gsc_impressions') or 0,
            'clicks': gsc_data.get('clicks') or gsc_data.get('gsc_clicks') or 0,
            'position': gsc_data.get('position') or gsc_data.get('avg_position') or gsc_data.get('gsc_position') or 0,
        }

        gsc_metrics_by_url[page_url] = metrics

    for page_id, page_obj in page_by_id.items():
        normalized_url = _normalize_url(page_obj.url)
        if normalized_url in gsc_metrics_by_url:
            gsc_metrics_by_page_id[page_id] = gsc_metrics_by_url[normalized_url]

    silos = list(SiloDefinition.objects.filter(site=site, status='active').order_by('name'))
    silo_ids = [s.id for s in silos]

    assignments_by_silo = defaultdict(list)
    if silo_ids:
        assignments = KeywordAssignment.objects.filter(
            site=site,
            status='active',
            silo_id__in=silo_ids,
        ).values('silo_id', 'page_id', 'page_url', 'page_type')

        for row in assignments:
            assignments_by_silo[row['silo_id']].append(row)

    link_pairs = set(
        InternalLink.objects
        .filter(site=site, is_valid=True, target_page__isnull=False)
        .values_list('source_page_id', 'target_page_id')
    )

    assigned_page_ids = set()
    assigned_page_urls = set()
    silos_payload = []

    for silo in silos:
        silo_assignments = assignments_by_silo.get(silo.id, [])
        unique_pages = []
        seen_ids = set()
        seen_urls = set()

        for assignment in silo_assignments:
            page_obj = None
            page_id = assignment.get('page_id')
            page_url = _normalize_url(assignment.get('page_url') or '')

            if page_id and page_id in page_by_id:
                page_obj = page_by_id[page_id]
            elif page_url and page_url in page_by_url:
                page_obj = page_by_url[page_url]

            if not page_obj:
                continue

            if page_obj.id in seen_ids or _normalize_url(page_obj.url) in seen_urls:
                continue

            seen_ids.add(page_obj.id)
            seen_urls.add(_normalize_url(page_obj.url))
            unique_pages.append((page_obj, (assignment.get('page_type') or '').lower()))

            assigned_page_ids.add(page_obj.id)
            assigned_page_urls.add(_normalize_url(page_obj.url))

        pillar_page = None
        if silo.hub_page_id and silo.hub_page_id in page_by_id:
            pillar_page = page_by_id[silo.hub_page_id]
        elif _normalize_url(silo.hub_page_url) in page_by_url:
            pillar_page = page_by_url[_normalize_url(silo.hub_page_url)]
        else:
            for page_obj, assigned_type in unique_pages:
                if assigned_type in {'hub', 'pillar'}:
                    pillar_page = page_obj
                    break
            if not pillar_page and unique_pages:
                pillar_page = unique_pages[0][0]

        supporting_pages_payload = []
        linked_to_pillar_count = 0

        for page_obj, _assigned_type in unique_pages:
            if pillar_page and page_obj.id == pillar_page.id:
                continue

            linked_to_pillar = False
            if pillar_page:
                linked_to_pillar = (page_obj.id, pillar_page.id) in link_pairs
                if linked_to_pillar:
                    linked_to_pillar_count += 1

            gsc_metrics = gsc_metrics_by_page_id.get(page_obj.id) or gsc_metrics_by_url.get(_normalize_url(page_obj.url)) or {}
            supporting_pages_payload.append(
                _serialize_page(page_obj, gsc_metrics, include_linked_to_pillar=linked_to_pillar)
            )

        if supporting_pages_payload:
            coverage_score = int(round((linked_to_pillar_count / len(supporting_pages_payload)) * 100))
        else:
            coverage_score = 100

        missing_internal_links = max(0, len(supporting_pages_payload) - linked_to_pillar_count)

        pillar_payload = None
        if pillar_page:
            pillar_gsc = gsc_metrics_by_page_id.get(pillar_page.id) or gsc_metrics_by_url.get(_normalize_url(pillar_page.url)) or {}
            pillar_payload = _serialize_page(pillar_page, pillar_gsc)

        silos_payload.append({
            'id': silo.id,
            'name': silo.name,
            'pillar_page': pillar_payload,
            'supporting_pages': supporting_pages_payload,
            'coverage_score': coverage_score,
            'missing_internal_links': missing_internal_links,
        })

    orphaned_pages = []
    for page_obj in all_pages:
        normalized = _normalize_url(page_obj.url)
        if page_obj.id in assigned_page_ids or normalized in assigned_page_urls:
            continue

        metrics = gsc_metrics_by_page_id.get(page_obj.id) or gsc_metrics_by_url.get(normalized) or {}
        orphaned_pages.append({
            'id': page_obj.id,
            'title': page_obj.title,
            'url': page_obj.url,
            'impressions': int(metrics.get('impressions', 0) or 0),
            'clicks': int(metrics.get('clicks', 0) or 0),
            'position': float(metrics.get('position', 0) or 0),
        })

    payload = {
        'silos': silos_payload,
        'orphaned_pages': orphaned_pages,
        'total_silos': len(silos_payload),
        'total_pages': len(all_pages),
    }

    cache.set(cache_key, payload, timeout=120)
    return Response(payload)
