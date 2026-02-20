"""
API URL routing for siloq_backend.
All API endpoints are prefixed with /api/v1/
"""
from django.urls import path, include
from django.http import JsonResponse

# Health check endpoint
def health_check(request):
    return JsonResponse({"status": "healthy"})

# Lazy import wrapper to avoid AppRegistryNotReady
def verify_api_key_view(request):
    from integrations.sync import verify_api_key
    return verify_api_key(request)

# Conflict views (lazy)
def conflict_list_view(request):
    from seo.conflict_views import conflict_list
    return conflict_list(request)

def conflict_resolve_view(request, conflict_id):
    from seo.conflict_views import conflict_resolve
    return conflict_resolve(request, conflict_id)

def conflict_dismiss_view(request, conflict_id):
    from seo.conflict_views import conflict_dismiss
    return conflict_dismiss(request, conflict_id)

# Health views (lazy)
def health_score_list_view(request):
    from seo.health_views import health_score_list
    return health_score_list(request)

def health_score_now_view(request):
    from seo.health_views import health_score_now
    return health_score_now(request)

# Lifecycle views (lazy)
def lifecycle_queue_list_view(request):
    from seo.lifecycle_views import lifecycle_queue_list
    return lifecycle_queue_list(request)

def lifecycle_queue_execute_view(request, queue_id):
    from seo.lifecycle_views import lifecycle_queue_execute
    return lifecycle_queue_execute(request, queue_id)

def content_jobs_create_view(request):
    from seo.content_views import create_content_job
    return create_content_job(request)

def content_jobs_status_view(request, job_id):
    from seo.content_views import get_content_job_status
    return get_content_job_status(request, job_id)

# Lazy imports for keyword registry + validation endpoints
def _kw_validate(request):
    from seo.keyword_registry_views import keyword_validate
    return keyword_validate(request)

def _kw_assign(request):
    from seo.keyword_registry_views import keyword_assign
    return keyword_assign(request)

def _kw_reassign(request, pk):
    from seo.keyword_registry_views import keyword_reassign
    return keyword_reassign(request, pk)

def _kw_list(request):
    from seo.keyword_registry_views import keyword_list
    return keyword_list(request)

def _kw_bootstrap(request):
    from seo.keyword_registry_views import keyword_bootstrap
    return keyword_bootstrap(request)

def _val_preflight(request):
    from seo.validation_views import validate_preflight
    return validate_preflight(request)

def _val_post_gen(request):
    from seo.validation_views import validate_post_generation
    return validate_post_generation(request)

def _val_batch(request):
    from seo.validation_views import validate_batch
    return validate_batch(request)

def _lazy(module, attr):
    """Lazy view import to avoid AppRegistryNotReady."""
    def view(*args, **kwargs):
        import importlib
        mod = importlib.import_module(module)
        return getattr(mod, attr)(*args, **kwargs)
    return view

urlpatterns = [
    # Health check (no auth) - GET /api/v1/health/
    path('health/', health_check),
    # --- Redirects (Section 6) ---
    path('redirects/', _lazy('seo.redirect_views', 'redirect_list_create')),
    path('redirects/verify/', _lazy('seo.redirect_views', 'redirect_verify')),
    # --- Content Audit (Section 7) ---
    path('audit/run/', _lazy('seo.audit_views', 'audit_run')),
    path('audit/<uuid:audit_id>/', _lazy('seo.audit_views', 'audit_detail')),
    # --- Freshness Alerts (Section 8) ---
    path('freshness/alerts/', _lazy('seo.freshness_views', 'freshness_alert_list')),
    path('freshness/alerts/<uuid:alert_id>/snooze/', _lazy('seo.freshness_views', 'freshness_alert_snooze')),
    # --- Page Metadata (Section 9) ---
    path('pages/crawl/', _lazy('seo.metadata_views', 'pages_crawl')),
    path('pages/metadata/', _lazy('seo.metadata_views', 'pages_metadata_list')),
    # --- Silo Management (Section 10) ---
    path('silos/', _lazy('seo.silo_views', 'silo_list')),
    # Dashboard authentication
    path('auth/', include('accounts.urls')),
    # WordPress plugin: POST /api/v1/auth/verify with Bearer <api_key>
    path('auth/verify', verify_api_key_view),
    # API key management (site-specific keys)
    path('api-keys/', include('sites.api_key_urls')),
    # Account key management (master/agency keys)
    path('account-keys/', include('sites.account_key_urls')),
    # Site management
    path('sites/', include('sites.urls')),
    # Google Search Console integration
    path('gsc/', include('integrations.gsc_urls')),
    # WordPress integration endpoints (scans, page sync) - MUST be before pages/
    path('', include('integrations.urls')),
    # Page management (dashboard) - comes after integrations to avoid conflicts
    path('pages/', include('seo.urls')),
    # Content generation jobs (WordPress plugin compatibility)
    # AI Content Engine
    path('ai/', include('ai.urls')),
    path('content-jobs/', content_jobs_create_view),
    path('content-jobs/<str:job_id>/', content_jobs_status_view),
    # Billing and subscription management
    path('billing/', include('billing.urls')),
    # Conflicts (Anti-Cannibalization)
    path('conflicts/', conflict_list_view, name='conflict-list'),
    path('conflicts/<uuid:conflict_id>/resolve/', conflict_resolve_view, name='conflict-resolve'),
    path('conflicts/<uuid:conflict_id>/dismiss/', conflict_dismiss_view, name='conflict-dismiss'),
    # Content Health
    path('health/scores/', health_score_list_view, name='health-score-list'),
    path('health/score-now/', health_score_now_view, name='health-score-now'),
    # Lifecycle Queue
    path('lifecycle/queue/', lifecycle_queue_list_view, name='lifecycle-queue-list'),
    path('lifecycle/queue/<uuid:queue_id>/execute/', lifecycle_queue_execute_view, name='lifecycle-queue-execute'),
    # Keyword Registry (v2 spec endpoints)
    path('keywords/validate', _kw_validate),
    path('keywords/assign', _kw_assign),
    path('keywords/<uuid:pk>/reassign', _kw_reassign),
    path('keywords', _kw_list),
    path('keywords/bootstrap', _kw_bootstrap),
    # Content Validation (v2 spec endpoints)
    path('validate/preflight', _val_preflight),
    path('validate/post-generation', _val_post_gen),
    path('validate/batch', _val_batch),
]
