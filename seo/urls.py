"""
URL routing for SEO app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .pages import PageViewSet
from . import conflict_views

router = DefaultRouter()
router.register(r'', PageViewSet, basename='page')

urlpatterns = [
    path('', include(router.urls)),
    # Conflicts tab endpoints (11.3 - wire to Ahmad's endpoint)
    path('sites/<uuid:site_id>/conflicts/', conflict_views.conflicts_list, name='conflicts-list'),
    path('sites/<uuid:site_id>/conflicts/<uuid:conflict_id>/accept/', conflict_views.accept_recommendation, name='accept-recommendation'),
    path('sites/<uuid:site_id>/conflicts/<uuid:conflict_id>/dismiss/', conflict_views.dismiss_conflict, name='dismiss-conflict'),
    path('sites/<uuid:site_id>/conflicts/<uuid:conflict_id>/resolve/', conflict_views.resolve_conflict, name='resolve-conflict'),
]

# Content Recommendations URLs (to be included from sites/ namespace)
content_recommendations_urls = [
    path('content-recommendations/', get_content_recommendations, name='content-recommendations-list'),
    path('content-recommendations/<str:rec_id>/generate/', generate_from_recommendation, name='content-recommendations-generate'),
    path('content/approve/', approve_content, name='content-approve'),
]
