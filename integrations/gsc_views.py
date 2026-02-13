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
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote

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
GSC_API_BASE = 'https://searchconsole.googleapis.com/v1'

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
            if access_token and site.url:
                try:
                    headers = {'Authorization': f'Bearer {access_token}'}
                    gsc_resp = requests.get(f'{GSC_API_BASE}/sites', headers=headers, timeout=10)
                    if gsc_resp.status_code == 200:
                        gsc_sites = gsc_resp.json().get('siteEntry', [])
                        site_domain = site.url.lower().replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
                        for gs in gsc_sites:
                            gs_url = gs.get('siteUrl', '').lower().replace('www.', '')
                            if site_domain in gs_url or gs_url.rstrip('/').endswith(site_domain):
                                site.gsc_site_url = gs['siteUrl']
                                logger.info(f"GSC OAuth: auto-matched site URL: {gs['siteUrl']}")
                                break
                        if not site.gsc_site_url and gsc_sites:
                            # Fallback: use first available GSC property
                            site.gsc_site_url = gsc_sites[0]['siteUrl']
                            logger.info(f"GSC OAuth: no exact match, using first property: {site.gsc_site_url}")
                except Exception as e:
                    logger.warning(f"GSC OAuth: failed to auto-detect site URL: {e}")
            
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
    
    return Response({
        'site_id': site.id,
        'gsc_site_url': site.gsc_site_url,
        'date_range': {'start': start_date, 'end': end_date},
        'row_count': len(data),
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
        
        # If domain property fails, try URL property format and vice versa
        alt_url = None
        if site_url.startswith('sc-domain:'):
            domain = site_url.replace('sc-domain:', '')
            alt_url = f'https://{domain}/'
        elif site_url.startswith('http'):
            domain = site_url.replace('https://', '').replace('http://', '').rstrip('/')
            alt_url = f'sc-domain:{domain}'
        
        if alt_url:
            print(f"[GSC] Trying alternate format: {alt_url}", flush=True)
            encoded_alt = quote(alt_url, safe='')
            alt_api_url = f'{GSC_API_BASE}/sites/{encoded_alt}/searchAnalytics/query'
            response = requests.post(alt_api_url, headers=headers, json=payload)
            if response.status_code == 200:
                print(f"[GSC] Alternate format worked: {alt_url}", flush=True)
                # Fall through to process response below
            else:
                print(f"[GSC] Alternate also failed (HTTP {response.status_code})", flush=True)
                return []
        else:
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
