"""
URL routing for API keys.
"""
from rest_framework.routers import DefaultRouter
from .api_keys import APIKeyViewSet

router = DefaultRouter()
router.register(r'', APIKeyViewSet, basename='apikey')

urlpatterns = router.urls
