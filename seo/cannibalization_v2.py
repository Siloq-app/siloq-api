"""
Cannibalization Detection V2 — GSC Query-Level Engine
Per Siloq V1 spec Section 01.

True cannibalization = two or more pages receiving impressions for the EXACT
SAME GSC query string. NOT title/URL keyword overlap.
"""
import logging
import re
from collections import defaultdict
from urllib.parse import urlparse

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from sites.models import Site

logger = logging.getLogger(__name__)

_US_STATE_ABBREVS = frozenset({
    'al','ak','az','ar','ca','co','ct','de','fl','ga','hi','id','il','in','ia',
    'ks','ky','la','me','md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj',
    'nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt',
    'va','wa','wv','wi','wy',
})
_STOP_WORDS = frozenset({
    'the','and','for','with','our','your','all','how','what','why','page','home',
    'about','contact','services','service','blog','news','www','com','net','org',
    'index','php','html','htm',
})

def _url_tokens(url):
    path = urlparse(url).path.lower().strip('/')
    raw = re.split(r'[/\-_]', path)
    return {t for t in raw if t and len(t) > 1 and t not in _STOP_WORDS and not t.isdigit()}

def _has_different_location_modifiers(url1, url2):
    t1 = _url_tokens(url1)
    t2 = _url_tokens(url2)
    common = t1 & t2
    only1 = t1 - t2
    only2 = t2 - t1
    if not common:
        return False
    def has_location_signal(tokens):
        return bool(tokens & _US_STATE_ABBREVS) or any(len(t) >= 4 for t in tokens)
    return has_location_signal(only1) and has_location_signal(only2)

def _classify_severity(pages):
    positions = [p['avg_position'] for p in pages[:2] if p.get('avg_position')]
    if len(positions) < 2:
        return 'low'
    p1, p2 = positions[0], positions[1]
    if p1 <= 10 and p2 <= 10:
        return 'critical'
    if (p1 <= 10 and p2 <= 20) or (p2 <= 10 and p1 <= 20):
        return 'high'
    if p1 <= 30 and p2 <= 30:
        return 'medium'
    return 'low'

_SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}

def _generate_recommendation(query, pages, severity, location_diff):
    if location_diff:
        return (
            "These pages target different geographic areas for the same service. "
            "This is correct multi-location site architecture — not cannibalization. No action needed."
        )
    winner = pages[0]
    loser = pages[1]
    wu = winner['url'].split('/')[-2] or winner['url']
    lu = loser['url'].split('/')[-2] or loser['url']
    wp = int(winner['click_share'] * 100)
    lp = int(loser['click_share'] * 100)
    if severity == 'critical':
        return (
            f"Both pages compete directly on page 1 for '{query}'. "
            f"Make '{wu}' the canonical winner ({wp}% of impressions). "
            f"Retarget '{lu}' to a related but distinct keyword. "
            f"Add an internal link from '{lu}' to '{wu}' with '{query}' as anchor text. "
            f"Supporting content may resolve the split — see the Content Plan tab."
        )
    elif severity == 'high':
        return (
            f"'{wu}' leads with {wp}% of impressions for '{query}'. "
            f"'{lu}' is splitting {lp}% of traffic. "
            f"Link the lower-ranked page to the stronger page using '{query}' as anchor text."
        )
    return (
        f"Low-impact split for '{query}' ({lp}% on secondary page). "
        f"Monitor — consider supporting blog content to consolidate topical authority."
    )

def detect_cannibalization_from_gsc(gsc_rows, min_impressions=5):
    """
    Core detection engine. Pure function — no DB calls.
    Returns list of conflict dicts sorted by: active first, severity, total impressions.
    """
    query_map = defaultdict(list)
    for row in gsc_rows:
        q = (row.get('query') or '').strip().lower()
        if q:
            query_map[q].append(row)

    conflicts = []
    for query, rows in query_map.items():
        eligible = [r for r in rows if r.get('impressions', 0) >= min_impressions]
        if len(eligible) < 2:
            continue

        # Deduplicate URLs — keep best row per URL
        url_best = {}
        for r in eligible:
            url = (r.get('page_url') or r.get('page') or '').strip().rstrip('/')
            if url and (url not in url_best or r.get('impressions', 0) > url_best[url].get('impressions', 0)):
                url_best[url] = r

        if len(url_best) < 2:
            continue

        total_imps = sum(r.get('impressions', 0) for r in url_best.values())
        if not total_imps:
            continue

        pages = sorted([
            {
                'url': url,
                'impressions': r.get('impressions', 0),
                'clicks': r.get('clicks', 0),
                'avg_position': round(r.get('position', 0), 1),
                'click_share': round(r.get('impressions', 0) / total_imps, 3),
            }
            for url, r in url_best.items()
        ], key=lambda p: p['impressions'], reverse=True)

        severity = _classify_severity(pages)
        top_urls = [p['url'] for p in pages[:2]]
        location_diff = len(top_urls) == 2 and _has_different_location_modifiers(top_urls[0], top_urls[1])

        conflicts.append({
            'query': query,
            'severity': severity,
            'location_differentiation': location_diff,
            'auto_dismissed': location_diff,
            'total_impressions': total_imps,
            'competing_pages': pages,
            'recommendation': _generate_recommendation(query, pages, severity, location_diff),
        })

    conflicts.sort(key=lambda c: (
        1 if c['auto_dismissed'] else 0,
        _SEVERITY_ORDER.get(c['severity'], 3),
        -c['total_impressions'],
    ))
    return conflicts


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

    all_conflicts  = detect_cannibalization_from_gsc(normalized, min_impressions=min_impressions)
    active         = [c for c in all_conflicts if not c['auto_dismissed']]
    dismissed      = [c for c in all_conflicts if c['auto_dismissed']]

    if severity_filter:
        active = [c for c in active if c['severity'] in severity_filter]

    returned = active + (dismissed if include_dismissed else [])

    sev_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    for c in active:
        sev_counts[c['severity']] = sev_counts.get(c['severity'], 0) + 1

    return Response({
        'conflicts': returned,
        'meta': {
            'total':            len(all_conflicts),
            'active':           len(active),
            'auto_dismissed':   len(dismissed),
            'queries_analyzed': len({r['query'] for r in normalized}),
            'severity_counts':  sev_counts,
            'source':           'gsc_query_level',
        }
    })
