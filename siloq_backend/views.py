"""
Project-level views (e.g. health check).
"""
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_check(request):
    """
    Liveness check for load balancers and monitoring.
    GET /api/v1/health/ - returns 200 if the app is running.
    No authentication required.
    """
    return JsonResponse({"status": "ok", "service": "siloq-backend"})
