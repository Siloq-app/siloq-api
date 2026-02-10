"""
Custom permissions for WordPress integrations.
"""
import logging
from rest_framework import permissions

logger = logging.getLogger(__name__)


class IsAPIKeyAuthenticated(permissions.BasePermission):
    """
    Permission to allow API key authenticated requests.
    """
    def has_permission(self, request, view):
        logger.debug(f"IsAPIKeyAuthenticated checking, request.auth: {request.auth}")
        # Check if request was authenticated via API key
        if hasattr(request, 'auth') and isinstance(request.auth, dict):
            result = request.auth.get('auth_type') == 'api_key'
            logger.debug(f"auth_type check result: {result}")
            return result
        logger.debug("No request.auth or not dict")
        return False


class IsJWTOrAPIKeyAuthenticated(permissions.BasePermission):
    """
    Permission to allow either JWT (dashboard) or API key (WordPress) authentication.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
