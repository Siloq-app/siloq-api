"""
URL configuration for siloq_backend project.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def custom_404(request, exception=None):
    """Return JSON for 404 errors instead of HTML."""
    return JsonResponse({
        'error': 'Not found',
        'detail': 'The requested resource was not found.',
        'status': 404,
    }, status=404)


def custom_500(request):
    """Return JSON for 500 errors instead of HTML."""
    return JsonResponse({
        'error': 'Internal server error',
        'detail': 'An unexpected error occurred.',
        'status': 500,
    }, status=500)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('siloq_backend.api_urls')),
]

# Custom error handlers - return JSON instead of HTML
handler404 = custom_404
handler500 = custom_500
