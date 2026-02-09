"""
API URL routing for siloq_backend.
All API endpoints are prefixed with /api/v1/
"""
from django.urls import path, include
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def health_check(request):
    """Simple health check endpoint."""
    return JsonResponse({"status": "ok", "service": "siloq-backend"})


# Lazy import wrapper to avoid AppRegistryNotReady
# Must be csrf_exempt because it's called from WordPress plugin (external API client)
@csrf_exempt
def verify_api_key_view(request):
    from integrations.sync import verify_api_key
    return verify_api_key(request)

urlpatterns = [
    # Health check (no auth) - GET /api/v1/health/
    path("health/", health_check),
    # Dashboard authentication
    path("auth/", include("accounts.urls")),
    # WordPress plugin: POST /api/v1/auth/verify with Bearer <api_key>
    path("auth/verify", verify_api_key_view),
    # API key management
    path("api-keys/", include("sites.api_key_urls")),
    # Site management
    path("sites/", include("sites.urls")),
    # Page management
    path("pages/", include("seo.urls")),
    # Billing and subscriptions
    path("billing/", include("billing.urls")),
    # WordPress integration endpoints (scans, page sync)
    path("", include("integrations.urls")),
]

