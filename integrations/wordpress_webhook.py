"""
WordPress webhook integration for pushing content from Siloq API to WordPress sites.
"""
import json
import logging

import requests

logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT = 15  # seconds


def _get_site_api_key(site):
    """
    Get the active API key for a site to use as Bearer token.
    Returns the first active (non-revoked) API key or None.
    """
    try:
        api_key = site.api_keys.filter(revoked_at__isnull=True).first()
        if api_key:
            # The actual key is hashed in the database, but we need the full key.
            # For now, we'll use the key_prefix as a placeholder until proper key storage is implemented.
            # In production, you'd need to store the unhashed key securely or use a different auth mechanism.
            # For this implementation, we'll use the site_id as a temporary identifier.
            return f"sk_siloq_{api_key.key_prefix}"
    except Exception as e:
        logger.warning(f"Failed to retrieve API key for site {site.id}: {e}")
    return None


def create_wordpress_redirect(site, source_url: str, target_url: str, redirect_type: int = 301, reason: str = '') -> dict:
    """
    Create a redirect in WordPress via the Siloq plugin's REST API.
    
    POST {site.url}/wp-json/siloq/v1/redirects
    
    Args:
        site: Site model instance (must have .url and .api_keys)
        source_url: The URL to redirect from
        target_url: The URL to redirect to
        redirect_type: HTTP redirect code (301, 302, etc.)
        reason: Human-readable reason for the redirect
    
    Returns:
        dict with 'success' (bool), 'status_code' (int|None), 'error' (str|None),
        and optionally 'response' (parsed JSON from WP).
    """
    url = f"{site.url.rstrip('/')}/wp-json/siloq/v1/redirects"
    
    payload = {
        'source_url': source_url,
        'target_url': target_url,
        'redirect_type': redirect_type,
        'reason': reason,
    }
    
    headers = {
        'Content-Type': 'application/json',
    }
    
    # Add Bearer token authentication if available
    api_key = _get_site_api_key(site)
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=WEBHOOK_TIMEOUT)
        resp_data = None
        try:
            resp_data = resp.json()
        except Exception:
            pass
        
        if resp.status_code < 300:
            logger.info(
                "Redirect created in WP for site %s: %s -> %s (HTTP %s)",
                site.id, source_url, target_url, resp.status_code
            )
            return {
                'success': True,
                'status_code': resp.status_code,
                'response': resp_data,
                'error': None,
            }
        else:
            logger.warning(
                "Redirect creation failed for site %s — HTTP %s: %s",
                site.id, resp.status_code, resp.text[:500],
            )
            return {
                'success': False,
                'status_code': resp.status_code,
                'response': resp_data,
                'error': f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
    except requests.RequestException as exc:
        logger.error("Redirect API call to %s error: %s", url, exc)
        return {
            'success': False,
            'status_code': None,
            'response': None,
            'error': str(exc),
        }


def send_webhook_to_wordpress(site, event_type: str, data: dict) -> dict:
    """
    Send a webhook event to a WordPress site's Siloq plugin endpoint.

    Args:
        site: Site model instance (must have .url)
        event_type: e.g. 'content.create_draft'
        data: payload dict

    Returns:
        dict with 'success' (bool), 'status_code' (int|None), 'error' (str|None),
        and optionally 'response' (parsed JSON from WP).
    """
    url = f"{site.url.rstrip('/')}/wp-json/siloq/v1/webhook"

    payload = {
        'event_type': event_type,
        'site_id': str(site.id),
        'data': data,
    }

    body = json.dumps(payload)

    headers = {
        'Content-Type': 'application/json',
        'X-Siloq-Event': event_type,
        # HMAC signing deferred — WP plugin will verify via callback or
        # allowlist in a follow-up. For now send site_id so WP can confirm.
    }

    try:
        resp = requests.post(url, data=body, headers=headers, timeout=WEBHOOK_TIMEOUT)
        resp_data = None
        try:
            resp_data = resp.json()
        except Exception:
            pass

        if resp.status_code < 300:
            logger.info(
                "Webhook %s sent to %s — HTTP %s", event_type, url, resp.status_code
            )
            return {
                'success': True,
                'status_code': resp.status_code,
                'response': resp_data,
                'error': None,
            }
        else:
            logger.warning(
                "Webhook %s to %s failed — HTTP %s: %s",
                event_type, url, resp.status_code, resp.text[:500],
            )
            return {
                'success': False,
                'status_code': resp.status_code,
                'response': resp_data,
                'error': f"HTTP {resp.status_code}",
            }
    except requests.RequestException as exc:
        logger.error("Webhook %s to %s error: %s", event_type, url, exc)
        return {
            'success': False,
            'status_code': None,
            'response': None,
            'error': str(exc),
        }
