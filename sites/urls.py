"""
URL routing for sites app.
"""
from django.urls import path, include, re_path
from rest_framework.routers import DefaultRouter
from .sites import SiteViewSet

router = DefaultRouter()
router.register(r'', SiteViewSet, basename='site')

urlpatterns = [
    path('', include(router.urls)),
    # Nested billing endpoints: /sites/{site_id}/billing/...
    path('<int:site_id>/billing/', include('billing.urls')),
]
