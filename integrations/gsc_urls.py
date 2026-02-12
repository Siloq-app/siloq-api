"""
URL routes for Google Search Console integration.
"""
from django.urls import path
from . import gsc_views

urlpatterns = [
    # OAuth flow
    path('auth-url/', gsc_views.get_auth_url, name='gsc-auth-url'),
    path('callback/', gsc_views.oauth_callback, name='gsc-callback'),
    
    # GSC sites
    path('sites/', gsc_views.list_gsc_sites, name='gsc-sites'),
]

# Site-specific GSC endpoints (included in sites URLs)
site_gsc_patterns = [
    path('gsc/connect/', gsc_views.connect_gsc_site, name='site-gsc-connect'),
    path('gsc/data/', gsc_views.get_gsc_data, name='site-gsc-data'),
    path('gsc/analyze/', gsc_views.analyze_gsc_cannibalization, name='site-gsc-analyze'),
]
