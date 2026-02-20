"""
URL routing for SEO app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .pages import PageViewSet
from .content_recommendations import (
    get_content_recommendations,
    generate_from_recommendation,
    approve_content,
)

router = DefaultRouter()
router.register(r'', PageViewSet, basename='page')

urlpatterns = [
    path('', include(router.urls)),
]

# Content Recommendations URLs (to be included from sites/ namespace)
content_recommendations_urls = [
    path('content-recommendations/', get_content_recommendations, name='content-recommendations-list'),
    path('content-recommendations/<str:rec_id>/generate/', generate_from_recommendation, name='content-recommendations-generate'),
    path('content/approve/', approve_content, name='content-approve'),
]
