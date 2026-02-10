"""
Custom authentication for API key-based requests from WordPress plugin.
"""
import logging
from rest_framework import authentication, exceptions
from django.utils import timezone

logger = logging.getLogger(__name__)


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticate WordPress plugin requests using API keys.
    
    Supports API keys in:
    - Authorization header: "Bearer sk_siloq_xxx"
    - X-API-Key header: "sk_siloq_xxx"
    """
    
    def authenticate(self, request):
        # Lazy import to avoid AppRegistryNotReady
        from sites.models import APIKey
        
        api_key = None
        
        # Check Authorization header first
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        logger.debug(f"Auth header: {auth_header[:20]}...")
        if auth_header.startswith('Bearer '):
            api_key = auth_header.split('Bearer ')[1].strip()
            logger.debug(f"Extracted API key: {api_key[:20]}...")
        
        # Fall back to X-API-Key header
        if not api_key:
            api_key = request.META.get('HTTP_X_API_KEY', '').strip()
        
        if not api_key:
            logger.debug("No API key found in request")
            return None
        
        # API keys should start with 'sk_siloq_'
        if not api_key.startswith('sk_siloq_'):
            logger.debug(f"API key doesn't start with sk_siloq_: {api_key[:10]}...")
            return None
        
        try:
            # Hash the provided key and look it up
            key_hash = APIKey.hash_key(api_key)
            logger.debug(f"Looking up key hash: {key_hash[:16]}...")
            api_key_obj = APIKey.objects.select_related('site', 'site__user').get(
                key_hash=key_hash,
                is_active=True
            )
            logger.debug(f"Found API key for site: {api_key_obj.site.id}")
            
            # Check expiration
            if api_key_obj.expires_at and api_key_obj.expires_at < timezone.now():
                raise exceptions.AuthenticationFailed('API key has expired')
            
            # Mark as used
            api_key_obj.mark_used()
            
            # Return user and site info
            return (api_key_obj.site.user, {
                'api_key': api_key_obj,
                'site': api_key_obj.site,
                'auth_type': 'api_key'
            })
            
        except APIKey.DoesNotExist:
            logger.warning(f"API key not found in database")
            return None  # Return None for 401, not exception for 403
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return None  # Return None for 401
