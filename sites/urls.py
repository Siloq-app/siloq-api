"""
URL routing for sites app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .sites import SiteViewSet

router = DefaultRouter()
router.register(r'', SiteViewSet, basename='site')

urlpatterns = [
    path('', include(router.urls)),
]
