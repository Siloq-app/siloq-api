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
    classify_pages_roles,
)
from seo.differentiate_views import (
    differentiate_conflict,
    apply_differentiation,
)
from seo.redirect_views import create_redirect, list_redirects
from seo.slug_change_views import change_slug, bulk_change_slugs, list_slug_changes
from integrations.gsc_views import (
    connect_gsc_site, get_gsc_data, analyze_gsc_cannibalization, content_gaps,
    gsc_status, gsc_sync, gsc_pages, gsc_disconnect, gsc_properties,
)
from sites.sites import dashboard_fix_now, geo_score_page
from seo.cannibalization_v2 import get_cannibalization_conflicts
from seo.silo_health_views import silo_health_scores, silo_health_recalculate
from seo.silo_views import silo_map
from seo.page_analysis_views import (
    list_approvals,
    analyze_page,
    analyze_all_pages,
    list_analyses,
    get_analysis,
    approve_recommendations,
    apply_recommendations,
)
from seo.entity_extraction_views import extract_entities
from seo.entity_profile_views import entity_profile, sync_gbp
from seo.supporting_content_views import (
    supporting_content_gap,
    about_us_analysis,
    schema_inventory,
    generate_supporting_article,
    generate_snippet,
    suggest_content,
    content_pipeline,
    junk_page_feed,
    create_draft,
    image_suggestion,
    generate_image,
)
from seo.freshness_views import site_freshness, page_freshness
from seo.schema_graph_views import schema_graph, schema_graph_completeness, schema_graph_regenerate
from seo.internal_links_views import get_related_pages, suggest_widget_edit
from seo.site_audit_views import site_audit
from seo.views_intelligence import generate_site_intelligence, get_site_intelligence
from seo import goals_views

router = DefaultRouter()
router.register(r'', SiteViewSet, basename='site')

urlpatterns = [
    path('', include(router.urls)),
    # Content Recommendations
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
    path('<int:site_id>/classify-pages/', classify_pages_roles, name='site-classify-pages'),
    # Redirects
    path('<int:site_id>/redirects/', list_redirects, name='site-redirects'),
    path('<int:site_id>/redirects/create/', create_redirect, name='site-redirect-create'),
    # Slug Changes
    path('<int:site_id>/pages/<int:page_id>/change-slug/', change_slug, name='page-change-slug'),
    path('<int:site_id>/pages/bulk-change-slugs/', bulk_change_slugs, name='page-bulk-change-slugs'),
    path('<int:site_id>/slug-changes/', list_slug_changes, name='site-slug-changes'),
    # Conflict Differentiation
    path('<int:site_id>/conflicts/differentiate/', differentiate_conflict, name='conflict-differentiate'),
    path('<int:site_id>/conflicts/apply-differentiation/', apply_differentiation, name='conflict-apply-differentiation'),
    # Google Search Console
    path('<int:site_id>/gsc/status/', gsc_status, name='site-gsc-status'),
    path('<int:site_id>/gsc/connect/', connect_gsc_site, name='site-gsc-connect'),
    path('<int:site_id>/gsc/data/', get_gsc_data, name='site-gsc-data'),
    path('<int:site_id>/gsc/analyze/', analyze_gsc_cannibalization, name='site-gsc-analyze'),
    path('<int:site_id>/gsc/sync/', gsc_sync, name='site-gsc-sync'),
    path('<int:site_id>/gsc/pages/', gsc_pages, name='site-gsc-pages'),
    path('<int:site_id>/gsc/disconnect/', gsc_disconnect, name='site-gsc-disconnect'),
    path('<int:site_id>/gsc/properties/', gsc_properties, name='site-gsc-properties'),
    path('<int:site_id>/content-gaps/', content_gaps, name='site-content-gaps'),
    path('<int:site_id>/cannibalization/', get_cannibalization_conflicts, name='site-cannibalization-v2'),
    path('<int:site_id>/dashboard/fix-now/', dashboard_fix_now, name='dashboard-fix-now'),
    # Silo Health
    path('<int:site_id>/silo-health/', silo_health_scores, name='site-silo-health'),
    path('<int:site_id>/silo-health/recalculate/', silo_health_recalculate, name='site-silo-health-recalculate'),
    path('<int:site_id>/silo-map/', silo_map, name='site-silo-map'),
    # Phase 0.5: Entity Extraction
    path('<int:site_id>/pages/extract-entities/', extract_entities, name='page-extract-entities'),
    # Pages Content Optimization — Three-Layer Model (GEO + SEO + CRO)
    path('<int:site_id>/pages/analyze/', analyze_page, name='page-analyze'),
    path('<int:site_id>/pages/analyze-all/', analyze_all_pages, name='page-analyze-all'),

    path('<int:site_id>/freshness/', site_freshness, name='site-freshness'),
    path('<int:site_id>/pages/<int:page_id>/freshness/', page_freshness, name='page-freshness'),
    path('<int:site_id>/approvals/', list_approvals, name='site-approvals'),
    path('<int:site_id>/pages/analysis/', list_analyses, name='page-analysis-list'),
    path('<int:site_id>/pages/analysis/<int:analysis_id>/', get_analysis, name='page-analysis-detail'),
    path('<int:site_id>/pages/analysis/<int:analysis_id>/approve/', approve_recommendations, name='page-analysis-approve'),
    path('<int:site_id>/pages/analysis/<int:analysis_id>/apply/', apply_recommendations, name='page-analysis-apply'),
    # Site Entity Profile
    path('<int:site_id>/entity-profile/', entity_profile, name='site-entity-profile'),
    path('<int:site_id>/entity-profile/sync-gbp/', sync_gbp, name='site-entity-profile-sync-gbp'),
    # Supporting Content Gap Detection (Section 02)
    path('<int:site_id>/pages/<int:page_id>/supporting-content/', supporting_content_gap, name='page-supporting-content'),
    path('<int:site_id>/pages/<int:page_id>/supporting-content/generate/', generate_supporting_article, name='page-supporting-content-generate'),
    path('<int:site_id>/pages/<int:page_id>/generate-snippet/', generate_snippet, name='page-generate-snippet'),
    path('<int:site_id>/suggest-content/', suggest_content, name='site-suggest-content'),
    path('<int:site_id>/pages/create-draft/', create_draft, name='page-create-draft'),
    path('<int:site_id>/content-pipeline/', content_pipeline, name='site-content-pipeline'),
    path('<int:site_id>/junk-pages/', junk_page_feed, name='site-junk-pages'),
    # About Us Intelligence (Section 05)
    path('<int:site_id>/pages/<int:page_id>/about-analysis/', about_us_analysis, name='page-about-analysis'),
    # Image Suggestion + Generation
    path('<int:site_id>/pages/<int:page_id>/image-suggestion/', image_suggestion, name='page-image-suggestion'),
    path('<int:site_id>/generate-image/', generate_image, name='site-generate-image'),
    # Schema Inventory — show existing + recommended + generated (Section 03)
    path('<int:site_id>/pages/analysis/<int:analysis_id>/schema/', schema_inventory, name='page-schema-inventory'),
    # Schema Graph — GEO-first full entity graph endpoint (AI-crawler optimized)
    path('<int:site_id>/schema-graph/', schema_graph, name='site-schema-graph'),
    path('<int:site_id>/schema-graph/completeness/', schema_graph_completeness, name='site-schema-graph-completeness'),
    path('<int:site_id>/schema-graph/regenerate/', schema_graph_regenerate, name='site-schema-graph-regenerate'),
    # Internal Linking Context (Reverse Silo)
    path('<int:site_id>/pages/<int:page_id>/related-pages/', get_related_pages, name='page-related-pages'),
    path('<int:site_id>/pages/<int:page_id>/suggest-widget-edit/', suggest_widget_edit, name='page-suggest-widget-edit'),
    # Site Audit — Track 2 scoring engine + AI recommendations
    path('<int:site_id>/audit/', site_audit, name='site-audit'),
    # Site Intelligence — Claude analysis: hub/spoke/orphan classification + content gaps
    path('<int:site_id>/intelligence/', get_site_intelligence, name='site-intelligence-get'),
    path('<int:site_id>/intelligence/generate', generate_site_intelligence, name='site-intelligence-generate'),
    # GEO Score — AI-crawler optimization scoring for a single page
    path('<int:site_id>/pages/<int:page_id>/geo-score/', geo_score_page, name='page-geo-score'),
    # Site Goals — owner goal configuration
    path('<int:site_id>/goals/', goals_views.site_goals, name='site-goals'),
]
