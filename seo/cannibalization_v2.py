"""
Cannibalization Detection V2 — GSC Query-Level Engine
Per Siloq V1 spec Section 01.

True cannibalization = two or more pages receiving impressions for the EXACT
SAME GSC query string. NOT title/URL keyword overlap.

Detection logic lives in integrations.gsc_views.detect_cannibalization_from_gsc.
"""
import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from integrations.gsc_views import (
    _get_valid_access_token,
    _fetch_search_analytics,
    detect_cannibalization_from_gsc,
)
from sites.models import Site

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_cannibalization_conflicts(request, site_id):
    """
    GSC query-level cannibalization detection.
    GET /api/v1/sites/{id}/cannibalization/

    Query params:
      include_dismissed=true   — include auto-dismissed location-differentiated conflicts
      min_impressions=5        — minimum impressions per page to consider (default 5)
      severity=critical,high   — comma-separated severity filter
    """
    site = Site.objects.filter(id=site_id, user=request.user).first()
    if not site:
        return Response({'error': 'Site not found'}, status=404)

    if not site.gsc_site_url or not site.gsc_refresh_token:
        return Response({
            'error': 'Google Search Console not connected for this site.',
            'action': 'Connect GSC in Settings to enable cannibalization detection.',
        }, status=400)

    try:
        from integrations.gsc_views import _get_valid_access_token, _fetch_search_analytics
        access_token = _get_valid_access_token(site)
        if not access_token:
            return Response({'error': 'GSC token expired — reconnect GSC in Settings.'}, status=401)
        gsc_rows = _fetch_search_analytics(
            access_token=access_token,
            site_url=site.gsc_site_url,
            dimensions=['query', 'page'],
            row_limit=5000,
        )
    except Exception as exc:
        logger.warning('GSC fetch failed for site %s: %s', site_id, exc)
        return Response({'error': f'Failed to fetch GSC data: {exc}'}, status=502)

    if not gsc_rows:
        return Response({
            'conflicts': [],
            'meta': {'total': 0, 'active': 0, 'auto_dismissed': 0,
                     'message': 'No GSC data available for the last 28 days.'}
        })

    normalized = [
        {
            'query':      row.get('query', ''),
            'page_url':   row.get('page', row.get('page_url', '')),
            'clicks':     row.get('clicks', 0),
            'impressions':row.get('impressions', 0),
            'position':   row.get('position', 0),
        }
        for row in gsc_rows
    ]

    include_dismissed = request.query_params.get('include_dismissed', '').lower() == 'true'
    min_impressions   = int(request.query_params.get('min_impressions', 5))
    severity_filter   = [s.strip() for s in request.query_params.get('severity', '').split(',') if s.strip()]

    all_conflicts = detect_cannibalization_from_gsc(normalized, min_impressions=min_impressions)
    active = [c for c in all_conflicts if not c['dismissed']]
    dismissed = [c for c in all_conflicts if c['dismissed']]

    if severity_filter:
        active = [c for c in active if c['severity'] in severity_filter]

    returned = active + (dismissed if include_dismissed else [])

    sev_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    for c in active:
        sev_counts[c['severity']] = sev_counts.get(c['severity'], 0) + 1

    return Response({
        'conflicts': returned,
        'meta': {
            'total': len(all_conflicts),
            'active': len(active),
            'auto_dismissed': len(dismissed),
            'queries_analyzed': len({r['query'] for r in normalized}),
            'severity_counts':  sev_counts,
            'source':           'gsc_query_level',
        }
    })
