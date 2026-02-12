"""
URL routing for WordPress integrations.
Note: These URLs are included at /api/v1/ level, so paths here are relative to that.
"""
from django.urls import path

# Import views directly - DRF decorators properly applied
from .sync import sync_page, sync_seo_data
from .scans import create_scan, get_scan, get_scan_report
from .seo_analysis import (
    health_summary,
    cannibalization_issues,
    link_opportunities,
    contextual_spoke_generation,
    link_insertion
)

urlpatterns = [
    # API key verification (mounted separately in api_urls.py)
    # WordPress page sync - support both with and without trailing slash
    path('pages/sync/', sync_page, name='sync-page'),
    path('pages/sync', sync_page, name='sync-page-no-slash'),  # For WordPress plugin compatibility
    path('pages/<int:page_id>/seo-data/', sync_seo_data, name='sync-seo-data'),
    path('pages/<int:page_id>/seo-data', sync_seo_data, name='sync-seo-data-no-slash'),  # Support both
    # WordPress scanner endpoints
    path('scans/', create_scan, name='create-scan'),
    path('scans', create_scan, name='create-scan-no-slash'),  # Support both
    path('scans/<int:scan_id>/', get_scan, name='get-scan'),
    path('scans/<int:scan_id>', get_scan, name='get-scan-no-slash'),  # Support both
    path('scans/<int:scan_id>/report/', get_scan_report, name='get-scan-report'),
    path('scans/<int:scan_id>/report', get_scan_report, name='get-scan-report-no-slash'),  # Support both
    # SEO Analysis endpoints (#15-19)
    path('health/summary/', health_summary, name='health-summary'),
    path('health/summary', health_summary, name='health-summary-no-slash'),  # Support both
    path('analysis/cannibalization/', cannibalization_issues, name='cannibalization-issues'),
    path('analysis/cannibalization', cannibalization_issues, name='cannibalization-issues-no-slash'),  # Support both
    path('analysis/link-opportunities/', link_opportunities, name='link-opportunities'),
    path('analysis/link-opportunities', link_opportunities, name='link-opportunities-no-slash'),  # Support both
    path('analysis/spoke-generation/', contextual_spoke_generation, name='spoke-generation'),
    path('analysis/spoke-generation', contextual_spoke_generation, name='spoke-generation-no-slash'),  # Support both
    path('analysis/link-insertion/', link_insertion, name='link-insertion'),
    path('analysis/link-insertion', link_insertion, name='link-insertion-no-slash'),  # Support both
]
