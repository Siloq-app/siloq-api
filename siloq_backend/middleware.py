"""
Custom middleware for siloq_backend.
"""
from django.middleware.common import CommonMiddleware


class APICommonMiddleware(CommonMiddleware):
    """
    Custom CommonMiddleware that disables APPEND_SLASH for API routes.
    This prevents redirect issues with POST requests to API endpoints.
    """
    def should_redirect_with_slash(self, request):
        # Skip APPEND_SLASH for all /api/ routes
        if request.path.startswith('/api/'):
            return False
        return super().should_redirect_with_slash(request)
