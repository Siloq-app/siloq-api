"""
Custom authentication for API key-based requests from WordPress plugin.
"""
import logging
from rest_framework import authentication, exceptions
from django.utils import timezone

logger = logging.getLogger(__name__)


def _extract_api_key(request):
    """Extract API key from request headers."""
    # Check Authorization header first
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        return auth_header.split('Bearer ')[1].strip()
    # Fall back to X-API-Key header
    return request.META.get('HTTP_X_API_KEY', '').strip() or None


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticate WordPress plugin requests using API keys.
    
    Supports both:
    - Site keys (sk_siloq_xxx) → scoped to a specific site
    - Account keys (ak_siloq_xxx) → works across all user's sites, auto-creates sites
    
    Keys can be in:
    - Authorization header: "Bearer sk_siloq_xxx" or "Bearer ak_siloq_xxx"
    - X-API-Key header: "sk_siloq_xxx" or "ak_siloq_xxx"
    """
    
    def authenticate(self, request):
        api_key = _extract_api_key(request)
        if not api_key:
            return None
        
        # Try site key first
        if api_key.startswith('sk_siloq_'):
            return self._authenticate_site_key(api_key, request)
        
        # Try account key
        if api_key.startswith('ak_siloq_'):
            return self._authenticate_account_key(api_key, request)
        
        return None
    
    def _authenticate_site_key(self, api_key, request):
        """Authenticate with a site-specific API key."""
        from sites.models import APIKey
        
        try:
            key_hash = APIKey.hash_key(api_key)
            api_key_obj = APIKey.objects.select_related('site', 'site__user').get(
                key_hash=key_hash,
                is_active=True
            )
            
            if api_key_obj.expires_at and api_key_obj.expires_at < timezone.now():
                raise exceptions.AuthenticationFailed('API key has expired')
            
            api_key_obj.mark_used()
            
            return (api_key_obj.site.user, {
                'api_key': api_key_obj,
                'site': api_key_obj.site,
                'auth_type': 'site_key'
            })
            
        except APIKey.DoesNotExist:
            logger.warning("Site API key not found in database")
            return None
        except Exception as e:
            logger.error(f"Site key auth error: {e}")
            return None
    
    def _authenticate_account_key(self, api_key, request):
        """
        Authenticate with an account-level master key.
        Auto-resolves or creates the site based on the request's site_url.
        """
        from sites.models import AccountKey, Site
        
        try:
            key_hash = AccountKey.hash_key(api_key)
            account_key = AccountKey.objects.select_related('user').get(
                key_hash=key_hash,
                is_active=True
            )
            
            if account_key.expires_at and account_key.expires_at < timezone.now():
                raise exceptions.AuthenticationFailed('Account key has expired')
            
            account_key.mark_used()
            
            # Try to resolve the site from the request
            site = None
            site_url = (
                request.data.get('site_url') or
                request.data.get('siteUrl') or
                request.META.get('HTTP_X_SITE_URL', '')
            ).strip()
            
            if site_url:
                # Normalize URL for matching
                normalized = site_url.lower().replace('http://', 'https://').rstrip('/')
                site = Site.objects.filter(
                    user=account_key.user,
                    url__icontains=normalized.replace('https://', '').replace('www.', '')
                ).first()
                
                # Auto-create site if not found
                if not site:
                    from urllib.parse import urlparse
                    parsed = urlparse(site_url if '://' in site_url else f'https://{site_url}')
                    domain = parsed.hostname or site_url
                    site = Site.objects.create(
                        user=account_key.user,
                        name=domain,
                        url=f"https://{domain}",
                    )
                    logger.info(f"Account key auto-created site: {site.name} (id={site.id})")
            
            if not site:
                # Fall back to user's first site
                site = Site.objects.filter(user=account_key.user).first()
            
            return (account_key.user, {
                'account_key': account_key,
                'site': site,
                'auth_type': 'account_key',
                'auto_create': True,
            })
            
        except AccountKey.DoesNotExist:
            logger.warning("Account API key not found in database")
            return None
        except Exception as e:
            logger.error(f"Account key auth error: {e}")
            return None
