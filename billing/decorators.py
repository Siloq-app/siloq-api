"""
Reusable decorator for AI action handlers that consume credits.
"""
from functools import wraps
from rest_framework.response import Response
from .models import SiteCredits

BULK_COST = 5  # All site-level/bulk operations cost 5 credits flat
DEFAULT_COST = 1

ACTION_COSTS = {
    "auto_add_link": 1,
    "schema_generation": 1,
    "content_draft": 5,
    "widget_intelligence": 1,
    "bulk_operation": BULK_COST,
    "content_engine": BULK_COST,
    "site_audit": BULK_COST,
    "cannibalization_analysis": 2,
}


def requires_credits(action_type, site_id_kwarg="site_id"):
    """
    Decorator for API views that consume credits.
    Checks balance before allowing the action, deducts on success.
    Usage:
        @requires_credits("auto_add_link")
        def my_view(request, site_id):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            site_id = kwargs.get(site_id_kwarg) or request.data.get("site_id") or request.query_params.get("site_id")
            cost = ACTION_COSTS.get(action_type, DEFAULT_COST)

            try:
                from sites.models import Site
                site = Site.objects.get(id=site_id, user=request.user)
                credits, _ = SiteCredits.objects.get_or_create(site=site, defaults={
                    "plan_tier": "free_trial",
                    "is_trial": True,
                    "trial_actions_remaining": 25,
                })
            except Exception:
                return Response({
                    "detail": "Could not verify credits for this site.",
                    "credits_error": True,
                }, status=400)

            if not credits.can_use(cost):
                return Response({
                    "detail": "You have used all your AI actions for this period.",
                    "credits_exhausted": True,
                    "balance": credits.effective_balance,
                    "plan_tier": credits.plan_tier,
                    "upgrade_url": "/billing/upgrade/",
                }, status=402)

            # Execute the view
            response = func(request, *args, **kwargs)

            # Only deduct on success (2xx)
            if hasattr(response, "status_code") and 200 <= response.status_code < 300:
                credits.deduct(cost=cost, action_type=action_type)

            return response
        return wrapper
    return decorator
