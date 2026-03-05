"""
schema_graph_views.py

GET /api/v1/sites/{site_id}/schema-graph/

Returns the complete JSON-LD schema graph for the site as a single document.
AI-crawler optimized: Content-Type: application/ld+json, sub-200ms cached.

Cache key:    siloq_schema_graph_{site_id}
TTL:          3600 seconds (1 hour)
Invalidation: post_save on SiteEntityProfile (see signal at bottom of file)
"""

from __future__ import annotations

import json
import logging

from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site
from rest_framework.permissions import IsAuthenticated
from seo.models import Page, SiteEntityProfile
from seo.schema_graph_builder import build_schema_graph, compute_completeness

logger = logging.getLogger(__name__)

CACHE_TTL = 3600  # 1 hour
CACHE_KEY_PREFIX = 'siloq_schema_graph_'


def _cache_key(site_id: int) -> str:
    return f'{CACHE_KEY_PREFIX}{site_id}'


def invalidate_schema_graph_cache(site_id: int) -> None:
    """Call this whenever entity profile or page analysis is updated."""
    cache.delete(_cache_key(site_id))
    logger.debug('Schema graph cache invalidated for site %s', site_id)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def schema_graph(request, site_id: int):
    """
    GET /api/v1/sites/{site_id}/schema-graph/

    Returns the complete JSON-LD schema graph for the site.
    Response is Content-Type: application/ld+json.

    Headers:
        X-Siloq-Cache: HIT | MISS
        X-Siloq-Completeness: <0-100>  (entity completeness score)
    """
    site = get_object_or_404(Site, pk=site_id)

    cache_key     = _cache_key(site_id)
    cached_result = cache.get(cache_key)
    cache_status  = 'HIT' if cached_result else 'MISS'

    if cached_result:
        graph_json  = cached_result['graph_json']
        completeness = cached_result['completeness']
    else:
        # Load entity profile
        try:
            profile = SiteEntityProfile.objects.get(site=site)
        except SiteEntityProfile.DoesNotExist:
            return Response(
                {'error': 'Entity profile not found. Complete your business profile to generate the schema graph.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Load published, indexable pages
        pages = list(
            Page.objects.filter(
                site=site,
                status='publish',
                is_noindex=False,
            ).only(
                'id', 'url', 'title', 'page_type_classification',
                'is_noindex', 'status',
            )
        )

        graph_doc = build_schema_graph(site, profile, pages)
        graph_json = json.dumps(graph_doc, indent=2, ensure_ascii=False)

        completeness = compute_completeness(site, profile)

        cache.set(cache_key, {
            'graph_json':   graph_json,
            'completeness': completeness,
        }, CACHE_TTL)

    response = HttpResponse(
        graph_json,
        content_type='application/ld+json; charset=utf-8',
    )
    response['X-Siloq-Cache']        = cache_status
    response['X-Siloq-Completeness'] = str(completeness.get('score', 0))
    response['Access-Control-Allow-Origin'] = '*'  # AI crawlers need CORS
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def schema_graph_completeness(request, site_id: int):
    """
    GET /api/v1/sites/{site_id}/schema-graph/completeness/

    Returns entity completeness score + missing fields without generating the full graph.
    Used by the WP plugin admin metabox card.
    """
    site = get_object_or_404(Site, pk=site_id)

    try:
        profile = SiteEntityProfile.objects.get(site=site)
    except SiteEntityProfile.DoesNotExist:
        return Response({
            'score':   0,
            'present': [],
            'missing': [
                'Business name', 'Street address', 'City', 'State',
                'Phone number', 'Business hours', 'Logo URL',
                'Service cities', 'Founding year', 'Business type',
            ],
        })

    completeness = compute_completeness(site, profile)
    completeness['endpoint_url'] = request.build_absolute_uri(
        f'/api/v1/sites/{site_id}/schema-graph/'
    )
    completeness['last_generated'] = cache.get(f'{CACHE_KEY_PREFIX}{site_id}_timestamp')

    return Response(completeness)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def schema_graph_regenerate(request, site_id: int):
    """
    POST /api/v1/sites/{site_id}/schema-graph/regenerate/

    Busts the cache and rebuilds the schema graph immediately.
    Called by the "Regenerate Graph" button in the WP plugin metabox.
    """
    invalidate_schema_graph_cache(site_id)
    return Response({'status': 'cache_cleared', 'message': 'Schema graph cache cleared. Next request will rebuild.'})


# ─── Cache invalidation signal ────────────────────────────────────────────────

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=SiteEntityProfile)
def _on_entity_profile_save(sender, instance, **kwargs):
    """Invalidate schema graph cache whenever the entity profile is saved."""
    if instance.site_id:
        invalidate_schema_graph_cache(instance.site_id)
