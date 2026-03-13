from django.contrib import admin
from .models import SiteCredits, CreditTransaction


@admin.register(SiteCredits)
class SiteCreditsAdmin(admin.ModelAdmin):
    list_display = ["site", "plan_tier", "effective_balance", "monthly_allowance", "is_trial", "trial_actions_remaining", "lifetime_used", "reset_date"]
    list_filter = ["plan_tier", "is_trial"]
    search_fields = ["site__url"]
    readonly_fields = ["lifetime_used", "created_at", "updated_at"]


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ["site_credits", "action_type", "cost", "note", "created_at"]
    list_filter = ["action_type"]
    readonly_fields = ["created_at"]
