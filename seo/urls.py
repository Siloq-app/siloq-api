"""
URL routing for SEO app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .pages import PageViewSet
from . import conflict_views
from . import content_plan_views

router = DefaultRouter()
router.register(r'', PageViewSet, basename='page')

urlpatterns = [
    path('', include(router.urls)),
    # Conflicts tab endpoints (11.3 - wire to Ahmad's endpoint)
    path('sites/<int:site_id>/conflicts/', conflict_views.conflicts_list, name='conflicts-list'),
    path('sites/<int:site_id>/conflicts/<int:conflict_id>/accept/', conflict_views.accept_recommendation, name='accept-recommendation'),
    path('sites/<int:site_id>/conflicts/<int:conflict_id>/dismiss/', conflict_views.dismiss_conflict, name='dismiss-conflict'),
    path('sites/<int:site_id>/conflicts/<int:conflict_id>/resolve/', conflict_views.resolve_conflict, name='resolve-conflict'),
    # Content Plan tab endpoints (11.5 - new tab)
    path('sites/<int:site_id>/content-plan/', content_plan_views.content_plan, name='content-plan'),
    path('sites/<int:site_id>/pages/<int:page_id>/supporting-content/', content_plan_views.supporting_content, name='supporting-content'),
    path('sites/<int:site_id>/pages/<int:page_id>/add-to-pipeline/', content_plan_views.add_to_pipeline, name='add-to-pipeline'),
    path('sites/<int:site_id>/content-pipeline/', content_plan_views.content_pipeline, name='content-pipeline'),
]
