"""
Admin configuration for billing models.
"""
from django.contrib import admin
from .models import ProjectAISettings, AIUsageLog, BillingEvent


@admin.register(ProjectAISettings)
class ProjectAISettingsAdmin(admin.ModelAdmin):
    list_display = ['site', 'mode', 'provider', 'trial_pages_used', 'billing_enabled', 'created_at']
    list_filter = ['mode', 'provider', 'billing_enabled']
    search_fields = ['site__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ['site', 'model', 'input_tokens', 'output_tokens', 'total_charge_usd', 'is_trial', 'created_at']
    list_filter = ['provider', 'is_trial', 'billing_mode']
    search_fields = ['site__name', 'content_job_id']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'


@admin.register(BillingEvent)
class BillingEventAdmin(admin.ModelAdmin):
    list_display = ['site', 'amount_usd', 'status', 'stripe_payment_intent_id', 'created_at']
    list_filter = ['status']
    search_fields = ['site__name', 'stripe_payment_intent_id', 'stripe_charge_id']
    readonly_fields = ['created_at', 'updated_at']
