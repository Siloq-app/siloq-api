"""
Google Search Console Integration

Uses OAuth 2.0 to fetch search analytics data for cannibalization detection.
"""
import os
import json
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from urllib.parse import urlencode

# OAuth Configuration (from environment)
GSC_CLIENT_ID = os.environ.get('GSC_CLIENT_ID', '')
GSC_CLIENT_SECRET = os.environ.get('GSC_CLIENT_SECRET', '')
GSC_REDIRECT_URI = os.environ.get('GSC_REDIRECT_URI', 'https://app.siloq.ai/auth/google/callback')

# Google OAuth endpoints
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GSC_API_BASE = 'https://searchconsole.googleapis.com/v1'

# Scopes needed
GSC_SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',
]


def get_auth_url(state: str = '') -> str:
    """
    Generate OAuth authorization URL for user to connect GSC.
    """
    params = {
        'client_id': GSC_CLIENT_ID,
        'redirect_uri': GSC_REDIRECT_URI,
        'scope': ' '.join(GSC_SCOPES),
        'response_type': 'code',
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    """
    Exchange authorization code for access and refresh tokens.
    """
    data = {
        'client_id': GSC_CLIENT_ID,
        'client_secret': GSC_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': GSC_REDIRECT_URI,
    }
    
    response = requests.post(GOOGLE_TOKEN_URL, data=data)
    
    if response.status_code != 200:
        return {'error': response.json()}
    
    return response.json()


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """
    Refresh an expired access token.
    """
    data = {
        'client_id': GSC_CLIENT_ID,
        'client_secret': GSC_CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
    }
    
    response = requests.post(GOOGLE_TOKEN_URL, data=data)
    
    if response.status_code != 200:
        return {'error': response.json()}
    
    return response.json()


def list_sites(access_token: str) -> List[Dict[str, str]]:
    """
    List all sites the user has access to in GSC.
    """
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(f'{GSC_API_BASE}/sites', headers=headers)
    
    if response.status_code != 200:
        return []
    
    data = response.json()
    return data.get('siteEntry', [])


def fetch_search_analytics(
    access_token: str,
    site_url: str,
    start_date: str = None,
    end_date: str = None,
    dimensions: List[str] = None,
    row_limit: int = 1000,
) -> List[Dict[str, Any]]:
    """
    Fetch search analytics data from GSC.
    
    Args:
        access_token: OAuth access token
        site_url: The site URL (e.g., 'https://crystallizedcouture.com/')
        start_date: Start date (YYYY-MM-DD), defaults to 90 days ago
        end_date: End date (YYYY-MM-DD), defaults to today
        dimensions: List of dimensions ['query', 'page', 'country', 'device', 'date']
        row_limit: Max rows to return (default 1000, max 25000)
    
    Returns:
        List of rows with keys, clicks, impressions, ctr, position
    """
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
    
    # URL encode the site URL for the API path
    encoded_site = requests.utils.quote(site_url, safe='')
    url = f'{GSC_API_BASE}/sites/{encoded_site}/searchAnalytics/query'
    
    payload = {
        'startDate': start_date,
        'endDate': end_date,
        'dimensions': dimensions,
        'rowLimit': row_limit,
        'startRow': 0,
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code != 200:
        return []
    
    data = response.json()
    rows = data.get('rows', [])
    
    # Transform to flat dict format
    results = []
    for row in rows:
        keys = row.get('keys', [])
        result = {
            'clicks': row.get('clicks', 0),
            'impressions': row.get('impressions', 0),
            'ctr': row.get('ctr', 0),
            'position': row.get('position', 0),
        }
        # Map keys to dimension names
        for i, dim in enumerate(dimensions):
            if i < len(keys):
                result[dim] = keys[i]
        results.append(result)
    
    return results


def fetch_cannibalization_data(access_token: str, site_url: str) -> List[Dict[str, Any]]:
    """
    Fetch GSC data specifically for cannibalization analysis.
    
    Returns query + page data with clicks, impressions, position.
    """
    return fetch_search_analytics(
        access_token=access_token,
        site_url=site_url,
        dimensions=['query', 'page'],
        row_limit=5000,  # Get lots of data for thorough analysis
    )
