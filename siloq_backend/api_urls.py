"""
API URL routing for siloq_backend.
All API endpoints are prefixed with /api/v1/
"""
from django.urls import path, include
from django.http import JsonResponse

# Health check endpoint
def health_check(request):
    return JsonResponse({"status": "healthy"})

# Lazy import wrapper to avoid AppRegistryNotReady
def verify_api_key_view(request):
    from integrations.sync import verify_api_key
    return verify_api_key(request)

urlpatterns = [
    # Health check (no auth) - GET /api/v1/health/
    path('health/', health_check),
    # Dashboard authentication
    path('auth/', include('accounts.urls')),
    # WordPress plugin: POST /api/v1/auth/verify with Bearer <api_key>
    path('auth/verify', verify_api_key_view),
    # API key management (site-specific keys)
    path('api-keys/', include('sites.api_key_urls')),
    # Account key management (master/agency keys)
    path('account-keys/', include('sites.account_key_urls')),
    # Site management
    path('sites/', include('sites.urls')),
    # Google Search Console integration
    path('gsc/', include('integrations.gsc_urls')),
    # WordPress integration endpoints (scans, page sync) - MUST be before pages/
    path('', include('integrations.urls')),
    # Page management (dashboard) - comes after integrations to avoid conflicts
    path('pages/', include('seo.urls')),
]
