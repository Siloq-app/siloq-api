"""
API endpoints for Silo Management (Section 10).
"""
import logging

from django.db.models import Count, Avg, Q, Subquery, OuterRef
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from seo.models import (
    SiloDefinition,
    KeywordAssignment,
    CannibalizationConflict,
    ConflictPage,
    ContentHealthScore,
)

logger = logging.getLogger(__name__)


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
