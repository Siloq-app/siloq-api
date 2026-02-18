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
    upload_content,
)
from seo.keyword_registry_views import (
    keyword_registry_list,
    keyword_registry_bootstrap,
    keyword_registry_check,
    keyword_registry_assign,
    keyword_registry_reassign,
)
from seo.classification_views import (
    classify_single_page,
    classify_all,
    manual_page_type_override,
)
from seo.differentiate_views import (
    differentiate_conflict,
    apply_differentiation,
)
from seo.redirect_views import create_redirect, list_redirects
from integrations.gsc_views import connect_gsc_site, get_gsc_data, analyze_gsc_cannibalization
from seo.silo_health_views import silo_health_scores, silo_health_recalculate

router = DefaultRouter()
router.register(r'', SiteViewSet, basename='site')

urlpatterns = [
    path('', include(router.urls)),
    # Content Recommendations (nested under sites/{site_id}/)
    path('<int:site_id>/content-recommendations/', get_content_recommendations, name='site-content-recommendations'),
    path('<int:site_id>/content-recommendations/<str:rec_id>/generate/', generate_from_recommendation, name='site-content-recommendations-generate'),
    path('<int:site_id>/content/approve/', approve_content, name='site-content-approve'),
    path('<int:site_id>/content/upload/', upload_content, name='content-upload'),
    # Keyword Registry
    path('<int:site_id>/keyword-registry/', keyword_registry_list, name='keyword-registry-list'),
    path('<int:site_id>/keyword-registry/bootstrap/', keyword_registry_bootstrap, name='keyword-registry-bootstrap'),
    path('<int:site_id>/keyword-registry/check/', keyword_registry_check, name='keyword-registry-check'),
    path('<int:site_id>/keyword-registry/assign/', keyword_registry_assign, name='keyword-registry-assign'),
    path('<int:site_id>/keyword-registry/reassign/', keyword_registry_reassign, name='keyword-registry-reassign'),
    # Page Classification
    path('<int:site_id>/pages/<int:page_id>/classify/', classify_single_page, name='page-classify'),
    path('<int:site_id>/classify-all/', classify_all, name='site-classify-all'),
    path('<int:site_id>/pages/<int:page_id>/page-type/', manual_page_type_override, name='page-type-override'),
    # Redirects
    path('<int:site_id>/redirects/', list_redirects, name='site-redirects'),
    path('<int:site_id>/redirects/create/', create_redirect, name='site-redirect-create'),
    # Conflict Differentiation (AI-powered)
    path('<int:site_id>/conflicts/differentiate/', differentiate_conflict, name='conflict-differentiate'),
    path('<int:site_id>/conflicts/apply-differentiation/', apply_differentiation, name='conflict-apply-differentiation'),
    # Google Search Console (site-specific)
    path('<int:site_id>/gsc/connect/', connect_gsc_site, name='site-gsc-connect'),
    path('<int:site_id>/gsc/data/', get_gsc_data, name='site-gsc-data'),
    path('<int:site_id>/gsc/analyze/', analyze_gsc_cannibalization, name='site-gsc-analyze'),
    # Silo Health Score v2
    path('<int:site_id>/silo-health/', silo_health_scores, name='site-silo-health'),
    path('<int:site_id>/silo-health/recalculate/', silo_health_recalculate, name='site-silo-health-recalculate'),
]
