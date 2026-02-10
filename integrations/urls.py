"""
URL routing for WordPress integrations.
Note: These URLs are included at /api/v1/ level, so paths here are relative to that.
"""
from django.urls import path
from . import views

urlpatterns = [
    # (auth/verify is mounted at api_urls via path('auth/verify', include(...)); remainder is '')
    # WordPress page sync - trailing slashes to avoid redirects that lose CSRF exemption
    path('pages/sync/', views.sync_page, name='sync-page'),
    path('pages/<int:page_id>/seo-data/', views.sync_seo_data, name='sync-seo-data'),
    # WordPress scanner endpoints
    path('scans/', views.create_scan, name='create-scan'),
    path('scans/<int:scan_id>/', views.get_scan, name='get-scan'),
    path('scans/<int:scan_id>/report/', views.get_scan_report, name='get-scan-report'),
]
