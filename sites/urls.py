"""
URL routing for sites app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .sites import SiteViewSet
from seo.content_recommendations import (
    get_content_recommendations,
    generate_from_recommendation,
    approve_content,
)

router = DefaultRouter()
router.register(r'', SiteViewSet, basename='site')

urlpatterns = [
    path('', include(router.urls)),
    # Content Recommendations (nested under sites/{site_id}/)
    path('<int:site_id>/content-recommendations/', get_content_recommendations, name='site-content-recommendations'),
    path('<int:site_id>/content-recommendations/<str:rec_id>/generate/', generate_from_recommendation, name='site-content-recommendations-generate'),
    path('<int:site_id>/content/approve/', approve_content, name='site-content-approve'),
]
