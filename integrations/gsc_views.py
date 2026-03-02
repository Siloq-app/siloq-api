"""
Google Search Console OAuth Views

Provides endpoints for:
1. GET /api/v1/gsc/auth-url/ - Get OAuth URL to redirect user
2. GET /api/v1/gsc/callback/ - Handle OAuth callback
3. GET /api/v1/gsc/sites/ - List user's GSC sites
4. POST /api/v1/sites/{id}/gsc/connect/ - Connect GSC site to Siloq site
5. GET /api/v1/sites/{id}/gsc/data/ - Fetch GSC data for analysis
6. POST /api/v1/sites/{id}/gsc/analyze/ - Run cannibalization analysis on GSC data
"""
import os
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote, urlparse

import requests
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from sites.models import Site
from sites.analysis import analyze_gsc_data

logger = logging.getLogger(__name__)

# OAuth Configuration
GSC_CLIENT_ID = os.environ.get('GSC_CLIENT_ID', '')
GSC_CLIENT_SECRET = os.environ.get('GSC_CLIENT_SECRET', '')
GSC_REDIRECT_URI = os.environ.get('GSC_REDIRECT_URI', 'https://api.siloq.ai/api/v1/gsc/callback/')

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GSC_API_BASE = 'https://www.googleapis.com/webmasters/v3'

GSC_SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',
]


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_auth_url(request):
    """
    Get the Google OAuth URL for GSC authorization.
    
    GET /api/v1/gsc/auth-url/?site_id=5
    
    Returns: { "auth_url": "https://accounts.google.com/o/oauth2/auth?..." }
    """
    site_id = request.query_params.get('site_id')
    
    if not GSC_CLIENT_ID:
        return Response(
            {'error': 'GSC integration not configured'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    # State contains user ID and site ID for the callback
    state = json.dumps({
        'user_id': request.user.id,
        'site_id': site_id,
    })
    
    params = {
        'client_id': GSC_CLIENT_ID,
        'redirect_uri': GSC_REDIRECT_URI,
        'scope': ' '.join(GSC_SCOPES),
        'response_type': 'code',
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state,
    }
    
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    
    return Response({'auth_url': auth_url})


@api_view(['GET'])
@permission_classes([])  # No auth - this is the OAuth callback
def oauth_callback(request):
    """
    Handle Google OAuth callback.
    
    GET /api/v1/gsc/callback/?code=...&state=...
    
    Exchanges code for tokens and stores them on the site.
    Redirects back to dashboard.
    """
    code = request.query_params.get('code')
    state_str = request.query_params.get('state', '{}')
    error = request.query_params.get('error')
    
    if error:
        logger.error(f"GSC OAuth error: {error}")
        return redirect(f"{settings.FRONTEND_URL}/dashboard?gsc_error={error}")
    
    if not code:
        return redirect(f"{settings.FRONTEND_URL}/dashboard?gsc_error=no_code")
    
    try:
        state = json.loads(state_str)
        user_id = state.get('user_id')
        site_id = state.get('site_id')
    except:
        return redirect(f"{settings.FRONTEND_URL}/dashboard?gsc_error=invalid_state")
    
    # Exchange code for tokens
    token_data = {
        'client_id': GSC_CLIENT_ID,
        'client_secret': GSC_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': GSC_REDIRECT_URI,
    }
    
    print(f"[GSC] Exchanging code for tokens. site_id={site_id}, user_id={user_id}, redirect_uri={GSC_REDIRECT_URI}", flush=True)
    logger.info(f"GSC OAuth: exchanging code for tokens. site_id={site_id}, user_id={user_id}, redirect_uri={GSC_REDIRECT_URI}")
    
    token_response = requests.post(GOOGLE_TOKEN_URL, data=token_data)
    
    if token_response.status_code != 200:
        print(f"[GSC] Token exchange FAILED (HTTP {token_response.status_code}): {token_response.text}", flush=True)
        logger.error(f"GSC token exchange failed (HTTP {token_response.status_code}): {token_response.text}")
        error_detail = token_response.json().get('error_description', 'token_exchange_failed') if token_response.text else 'token_exchange_failed'
        return redirect(f"{settings.FRONTEND_URL}/dashboard?gsc_error=token_exchange_failed&detail={quote(error_detail)}")
    
    tokens = token_response.json()
    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')
    expires_in = tokens.get('expires_in', 3600)
    
    print(f"[GSC] Tokens received. has_access={bool(access_token)}, has_refresh={bool(refresh_token)}", flush=True)
    logger.info(f"GSC OAuth: tokens received. has_access={bool(access_token)}, has_refresh={bool(refresh_token)}")
    
    if not refresh_token:
        logger.warning("GSC OAuth: No refresh token received. User may need to re-authorize with prompt=consent.")
    
    # If site_id provided, store tokens and auto-detect GSC site URL
    if site_id:
        try:
            site = Site.objects.get(id=site_id, user_id=user_id)
            site.gsc_access_token = access_token
            if refresh_token:
                site.gsc_refresh_token = refresh_token
            site.gsc_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
            site.gsc_connected_at = timezone.now()
            
            # Auto-detect the matching GSC site URL from user's properties
            if access_token:
                try:
                    headers = {'Authorization': f'Bearer {access_token}'}
                    gsc_resp = requests.get(f'{GSC_API_BASE}/sites', headers=headers, timeout=10)
                    print(f"[GSC] Properties API response ({gsc_resp.status_code}): {gsc_resp.text[:500]}", flush=True)
                    if gsc_resp.status_code == 200:
                        gsc_sites = gsc_resp.json().get('siteEntry', [])
                        print(f"[GSC] Found {len(gsc_sites)} properties: {[gs.get('siteUrl') for gs in gsc_sites]}", flush=True)
                        
                        if site.url:
                            site_domain = site.url.lower().replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
                            for gs in gsc_sites:
                                gs_url = gs.get('siteUrl', '').lower().replace('www.', '')
                                gs_domain = gs_url.replace('https://', '').replace('http://', '').replace('sc-domain:', '').rstrip('/')
                                if site_domain == gs_domain or site_domain in gs_url or gs_url.rstrip('/').endswith(site_domain):
                                    site.gsc_site_url = gs['siteUrl']
                                    print(f"[GSC] Auto-matched: {gs['siteUrl']}", flush=True)
                                    break
                        
                        if not site.gsc_site_url and gsc_sites:
                            # Fallback: use first available GSC property
                            site.gsc_site_url = gsc_sites[0]['siteUrl']
                            print(f"[GSC] No exact match, using first property: {site.gsc_site_url}", flush=True)
                    else:
                        print(f"[GSC] Properties API FAILED ({gsc_resp.status_code})", flush=True)
                except Exception as e:
                    print(f"[GSC] Auto-detect error: {e}", flush=True)
            
            site.save()
            print(f"[GSC] SUCCESS: saved tokens for site {site_id}. gsc_site_url={site.gsc_site_url}", flush=True)
            logger.info(f"GSC OAuth: saved tokens for site {site_id}. gsc_site_url={site.gsc_site_url}")
            return redirect(f"{settings.FRONTEND_URL}/dashboard?gsc_connected=true&site_id={site_id}")
        except Site.DoesNotExist:
            print(f"[GSC] ERROR: Site {site_id} not found for user {user_id}", flush=True)
            logger.error(f"GSC OAuth: Site {site_id} not found for user {user_id}")
            return redirect(f"{settings.FRONTEND_URL}/dashboard?gsc_error=site_not_found")
        except Exception as e:
            print(f"[GSC] ERROR saving tokens: {e}", flush=True)
            return redirect(f"{settings.FRONTEND_URL}/dashboard?gsc_error=save_failed")
    
    # No site_id — redirect to site picker with temporary token
    return redirect(f"{settings.FRONTEND_URL}/dashboard?tab=search-console&gsc_callback=true")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_gsc_sites(request):
    """
    List all GSC sites the user has access to.
    
    GET /api/v1/gsc/sites/?access_token=...
    
    Returns: { "sites": [{"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"}] }
    """
    # Get access token from query param or from a connected site
    access_token = request.query_params.get('access_token')
    site_id = request.query_params.get('site_id')
    
    if not access_token and site_id:
        try:
            site = Site.objects.get(id=site_id, user=request.user)
            access_token = _get_valid_access_token(site)
        except Site.DoesNotExist:
            return Response({'error': 'Site not found'}, status=404)
    
    if not access_token:
        return Response({'error': 'No access token provided'}, status=400)
    
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(f'{GSC_API_BASE}/sites', headers=headers)
    
    if response.status_code != 200:
        return Response({'error': 'Failed to fetch GSC sites', 'details': response.json()}, status=response.status_code)
    
    data = response.json()
    return Response({'sites': data.get('siteEntry', [])})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def connect_gsc_site(request, site_id):
    """
    Connect a GSC property to a Siloq site.
    
    POST /api/v1/sites/{id}/gsc/connect/
    Body: { "gsc_site_url": "https://crystallizedcouture.com/", "access_token": "...", "refresh_token": "..." }
    """
    try:
        site = Site.objects.get(id=site_id, user=request.user)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=404)
    
    gsc_site_url = request.data.get('gsc_site_url')
    access_token = request.data.get('access_token')
    refresh_token = request.data.get('refresh_token')
    
    if not gsc_site_url:
        return Response({'error': 'gsc_site_url required'}, status=400)
    
    site.gsc_site_url = gsc_site_url
    if access_token:
        site.gsc_access_token = access_token
    if refresh_token:
        site.gsc_refresh_token = refresh_token
        site.gsc_token_expires_at = timezone.now() + timedelta(hours=1)
    
    site.save()

    # Trigger silo health recalculation on GSC connect — non-blocking
    try:
        from seo.silo_health import run_silo_health_for_site
        run_silo_health_for_site(site, trigger='gsc_connect')
    except Exception as _sh_err:
        logger.warning('Silo health recalculation failed after GSC connect (site %s): %s', site_id, _sh_err)

    return Response({
        'message': 'GSC connected successfully',
        'gsc_site_url': gsc_site_url,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_gsc_data(request, site_id):
    """
    Fetch GSC search analytics data for a site.
    
    GET /api/v1/sites/{id}/gsc/data/?days=90
    
    Returns raw query+page data for analysis.
    """
    try:
        site = Site.objects.get(id=site_id, user=request.user)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=404)
    
    if not site.gsc_site_url or not site.gsc_refresh_token:
        return Response({'error': 'GSC not connected for this site'}, status=400)
    
    access_token = _get_valid_access_token(site)
    if not access_token:
        return Response({'error': 'Failed to get GSC access token'}, status=401)
    
    days = int(request.query_params.get('days', 90))
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    # Fetch query+page data
    data = _fetch_search_analytics(
        access_token=access_token,
        site_url=site.gsc_site_url,
        start_date=start_date,
        end_date=end_date,
        dimensions=['query', 'page'],
        row_limit=5000,
    )
    
    # Aggregate totals for dashboard metrics
    total_clicks = sum(r.get('clicks', 0) for r in data)
    total_impressions = sum(r.get('impressions', 0) for r in data)
    avg_ctr = (total_clicks / total_impressions) if total_impressions > 0 else 0
    positions = [r.get('position', 0) for r in data if r.get('position', 0) > 0]
    avg_position = (sum(positions) / len(positions)) if positions else 0

    # Calculate position volatility (std dev of positions)
    if len(positions) > 1:
        mean_pos = avg_position
        variance = sum((p - mean_pos) ** 2 for p in positions) / len(positions)
        position_volatility = round(variance ** 0.5, 1)
    else:
        position_volatility = 0

    return Response({
        'site_id': site.id,
        'gsc_site_url': site.gsc_site_url,
        'date_range': {'start': start_date, 'end': end_date},
        'row_count': len(data),
        'totals': {
            'clicks': total_clicks,
            'impressions': total_impressions,
            'ctr': round(avg_ctr, 4),
            'position': round(avg_position, 1),
            'avg_position': round(avg_position, 1),
            'position_volatility': position_volatility,
            'clicks_delta': 0,
            'impressions_delta': 0,
            'ctr_delta': 0,
            'position_delta': 0,
            'volatility_delta': 0,
        },
        'data': data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_gsc_cannibalization(request, site_id):
    """
    Run cannibalization analysis on GSC data.
    
    POST /api/v1/sites/{id}/gsc/analyze/
    
    Fetches fresh GSC data and runs the analysis engine.
    """
    try:
        site = Site.objects.get(id=site_id, user=request.user)
    except Site.DoesNotExist:
        return Response({'error': 'Site not found'}, status=404)
    
    if not site.gsc_site_url or not site.gsc_refresh_token:
        return Response({'error': 'GSC not connected for this site'}, status=400)
    
    access_token = _get_valid_access_token(site)
    if not access_token:
        return Response({'error': 'Failed to get GSC access token'}, status=401)
    
    # Fetch GSC data
    gsc_data = _fetch_search_analytics(
        access_token=access_token,
        site_url=site.gsc_site_url,
        dimensions=['query', 'page'],
        row_limit=5000,
    )
    
    if not gsc_data:
        return Response({'error': 'No GSC data available'}, status=404)
    
    # Transform to format expected by analyze_gsc_data
    formatted_data = [
        {
            'query': row.get('query', ''),
            'page_url': row.get('page', ''),
            'clicks': row.get('clicks', 0),
            'impressions': row.get('impressions', 0),
            'position': row.get('position', 0),
        }
        for row in gsc_data
    ]
    
    # Run analysis
    issues = analyze_gsc_data(formatted_data)
    
    return Response({
        'site_id': site.id,
        'gsc_site_url': site.gsc_site_url,
        'queries_analyzed': len(gsc_data),
        'issues_found': len(issues),
        'issues': issues,
    })


# ── Cannibalization Detection (GSC-only, query-level) ─────────────────────────

_US_STATE_ABBREVS = frozenset({
    'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga', 'hi', 'id', 'il', 'in', 'ia',
    'ks', 'ky', 'la', 'me', 'md', 'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv', 'nh', 'nj',
    'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc', 'sd', 'tn', 'tx', 'ut', 'vt',
    'va', 'wa', 'wv', 'wi', 'wy',
})
_STOP_WORDS = frozenset({
    'the', 'and', 'for', 'with', 'our', 'your', 'all', 'how', 'what', 'why', 'page', 'home',
    'about', 'contact', 'services', 'service', 'blog', 'news', 'www', 'com', 'net', 'org',
    'index', 'php', 'html', 'htm',
})


def _url_to_path(url: str) -> str:
    """Extract path from URL: /olathe/ or /services/."""
    if not url:
        return '/'
    path = urlparse(url).path or '/'
    if not path.startswith('/'):
        path = '/' + path
    if path != '/' and not path.endswith('/'):
        path = path + '/'
    return path


def _url_tokens(url: str) -> set:
    path = urlparse(url).path.lower().strip('/')
    raw = re.split(r'[/\-_]', path)
    return {t for t in raw if t and len(t) > 1 and t not in _STOP_WORDS and not t.isdigit()}


def _has_different_location_modifiers(url1: str, url2: str) -> bool:
    """If competing pages have different location slugs (bonner-springs vs excelsior-springs) → Location Differentiation."""
    t1 = _url_tokens(url1)
    t2 = _url_tokens(url2)
    only1 = t1 - t2
    only2 = t2 - t1

    def has_location_signal(tokens):
        return bool(tokens & _US_STATE_ABBREVS) or any(len(t) >= 4 for t in tokens)

    return has_location_signal(only1) and has_location_signal(only2)


def _classify_severity(pages: list) -> str:
    """Severity based on position: Critical=both ≤10, High=one 1–10 other 11–20, Medium=both 11–30, Low=both >30."""
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


def _generate_recommendation(query: str, pages: list, severity: str, location_diff: bool) -> str:
    if location_diff:
        return (
            "These pages target different geographic areas for the same service. "
            "This is correct multi-location site architecture — not cannibalization. No action needed."
        )
    winner, loser = pages[0], pages[1]
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


def detect_cannibalization_from_gsc(gsc_rows: list, min_impressions: int = 5) -> list:
    """
    Cannibalization detection using GSC data only. No title/URL keyword matching.

    Logic:
    1. Pull all queries from GSC for the site
    2. For each query, get all pages with ≥min_impressions
    3. If 2+ pages for same query → cannibalizing query
    4. Severity: Critical=both ≤10, High=one 1–10 other 11–20, Medium=both 11–30, Low=both >30
    5. Group by QUERY (not by page)
    6. Location exception: different location slugs (bonner-springs vs excelsior-springs) → Location Differentiation

    Returns list of conflict dicts with: query, severity, competing_pages, location_differentiation, recommendation, dismissed.
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

        url_best = {}
        for r in eligible:
            raw_url = (r.get('page_url') or r.get('page') or '').strip().rstrip('/')
            if raw_url:
                url = _url_to_path(raw_url)
                if url not in url_best or r.get('impressions', 0) > url_best[url].get('impressions', 0):
                    url_best[url] = r

        if len(url_best) < 2:
            continue

        total_imps = sum(r.get('impressions', 0) for r in url_best.values())
        if not total_imps:
            continue

        competing_pages = sorted([
            {
                'url': url,
                'impressions': r.get('impressions', 0),
                'clicks': r.get('clicks', 0),
                'avg_position': round(r.get('position', 0), 1),
                'click_share': round(r.get('impressions', 0) / total_imps, 3),
            }
            for url, r in url_best.items()
        ], key=lambda p: p['impressions'], reverse=True)

        severity = _classify_severity(competing_pages)
        top_urls = [p['url'] for p in competing_pages[:2]]
        location_diff = len(top_urls) == 2 and _has_different_location_modifiers(top_urls[0], top_urls[1])

        conflicts.append({
            'query': query,
            'severity': severity,
            'competing_pages': competing_pages,
            'location_differentiation': location_diff,
            'recommendation': _generate_recommendation(query, competing_pages, severity, location_diff),
            'dismissed': location_diff,
        })

    _SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    conflicts.sort(key=lambda c: (
        1 if c['dismissed'] else 0,
        _SEVERITY_ORDER.get(c['severity'], 3),
        -sum(p['impressions'] for p in c['competing_pages']),
    ))
    return conflicts


def _get_valid_access_token(site) -> str:
    """Get a valid access token, refreshing if needed."""
    if site.gsc_token_expires_at and site.gsc_token_expires_at > timezone.now():
        return site.gsc_access_token
    
    if not site.gsc_refresh_token:
        return None
    
    # Refresh the token
    token_data = {
        'client_id': GSC_CLIENT_ID,
        'client_secret': GSC_CLIENT_SECRET,
        'refresh_token': site.gsc_refresh_token,
        'grant_type': 'refresh_token',
    }
    
    response = requests.post(GOOGLE_TOKEN_URL, data=token_data)
    
    if response.status_code != 200:
        logger.error(f"Token refresh failed: {response.text}")
        return None
    
    tokens = response.json()
    site.gsc_access_token = tokens.get('access_token')
    site.gsc_token_expires_at = timezone.now() + timedelta(seconds=tokens.get('expires_in', 3600))
    site.save()
    
    return site.gsc_access_token


def fetch_gsc_daily_data(
    access_token: str,
    site_url: str,
    days: int = 28
) -> list:
    """
    Fetch daily position data for flip-flop detection.
    
    Args:
        access_token: Valid GSC access token
        site_url: GSC property URL
        days: Number of days to fetch (default 28 for flip-flop detection)
    
    Returns:
        List of dicts with keys: date, query, page, position, clicks, impressions
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    # Fetch with date dimension included
    return _fetch_search_analytics(
        access_token=access_token,
        site_url=site_url,
        start_date=start_date,
        end_date=end_date,
        dimensions=['date', 'query', 'page'],
        row_limit=25000,  # Higher limit for daily data
    )


def _fetch_search_analytics(
    access_token: str,
    site_url: str,
    start_date: str = None,
    end_date: str = None,
    dimensions: list = None,
    row_limit: int = 1000,
) -> list:
    """Fetch search analytics data from GSC API."""
    if not start_date:
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    if not dimensions:
        dimensions = ['query', 'page']
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }
    
    encoded_site = quote(site_url, safe='')
    url = f'{GSC_API_BASE}/sites/{encoded_site}/searchAnalytics/query'
    
    payload = {
        'startDate': start_date,
        'endDate': end_date,
        'dimensions': dimensions,
        'rowLimit': row_limit,
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200:
        print(f"[GSC] API error for {site_url} (HTTP {response.status_code}): {response.text[:200]}", flush=True)
        
        # Try alternate URL formats — Google is picky about exact property URL
        domain = site_url.replace('https://', '').replace('http://', '').replace('sc-domain:', '').rstrip('/')
        alternates = []
        if site_url.startswith('sc-domain:'):
            alternates = [
                f'https://{domain}',        # no trailing slash
                f'https://{domain}/',        # with trailing slash
                f'https://www.{domain}/',    # www variant
            ]
        else:
            alternates = [
                site_url.rstrip('/'),                    # no trailing slash
                site_url.rstrip('/') + '/',              # with trailing slash
                f'sc-domain:{domain}',                   # domain property
                f'https://www.{domain}/',                # www variant
            ]
        # Remove the original URL we already tried
        alternates = [u for u in alternates if u != site_url]
        
        for alt_url in alternates:
            print(f"[GSC] Trying alternate format: {alt_url}", flush=True)
            encoded_alt = quote(alt_url, safe='')
            alt_api_url = f'{GSC_API_BASE}/sites/{encoded_alt}/searchAnalytics/query'
            response = requests.post(alt_api_url, headers=headers, json=payload)
            if response.status_code == 200:
                print(f"[GSC] Alternate format worked: {alt_url}", flush=True)
                break
            else:
                print(f"[GSC] Alternate failed (HTTP {response.status_code}): {alt_url}", flush=True)
        else:
            print(f"[GSC] All URL formats failed for {domain}", flush=True)
            return []
    
    data = response.json()
    rows = data.get('rows', [])
    
    results = []
    for row in rows:
        keys = row.get('keys', [])
        result = {
            'clicks': row.get('clicks', 0),
            'impressions': row.get('impressions', 0),
            'ctr': row.get('ctr', 0),
            'position': row.get('position', 0),
        }
        for i, dim in enumerate(dimensions):
            if i < len(keys):
                result[dim] = keys[i]
        results.append(result)
    
    return results
