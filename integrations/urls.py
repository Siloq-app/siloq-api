"""
URL routing for WordPress integrations.
Note: These URLs are included at /api/v1/ level, so paths here are relative to that.
"""
from django.urls import path

# Lazy view imports to avoid AppRegistryNotReady
def sync_page_view(request):
    from .sync import sync_page
    return sync_page(request)

def sync_seo_data_view(request, page_id):
    from .sync import sync_seo_data
    return sync_seo_data(request, page_id)

def create_scan_view(request):
    from .scans import create_scan
    return create_scan(request)

def get_scan_view(request, scan_id):
    from .scans import get_scan
    return get_scan(request, scan_id)

def get_scan_report_view(request, scan_id):
    from .scans import get_scan_report
    return get_scan_report(request, scan_id)

urlpatterns = [
    # API key verification (mounted separately in api_urls.py)
    # WordPress page sync
    path('pages/sync/', sync_page_view, name='sync-page'),
    path('pages/<int:page_id>/seo-data/', sync_seo_data_view, name='sync-seo-data'),
    # WordPress scanner endpoints
    path('scans/', create_scan_view, name='create-scan'),
    path('scans/<int:scan_id>/', get_scan_view, name='get-scan'),
    path('scans/<int:scan_id>/report/', get_scan_report_view, name='get-scan-report'),
]
