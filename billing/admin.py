from django.contrib import admin
from .models import Subscription, Payment, Usage


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'tier',
        'status',
        'is_staff_exempt',
        'stripe_customer_id',
        'stripe_subscription_id',
        'is_trial_active',
        'trial_days_remaining',
        'current_period_end',
        'created_at',
    )
    list_editable = ('is_staff_exempt',)
    list_filter = (
        'tier',
        'status',
        'is_staff_exempt',
        'created_at',
        'current_period_end',
    )
    search_fields = (
        'user__username',
        'user__email',
        'stripe_customer_id',
        'stripe_subscription_id',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
        'is_trial_active',
        'trial_days_remaining',
    )
    ordering = ('-created_at',)

    fieldsets = (
        ("User Info", {
            'fields': ('user',)
        }),
        ("Stripe Info", {
            'fields': (
                'stripe_customer_id',
                'stripe_subscription_id',
            )
        }),
        ("Subscription Details", {
            'fields': (
                'tier',
                'status',
                'is_staff_exempt',
                'current_period_start',
                'current_period_end',
            )
        }),
        ("Trial Info", {
            'fields': (
                'trial_started_at',
                'trial_ends_at',
                'trial_pages_limit',
                'trial_pages_used',
                'is_trial_active',
                'trial_days_remaining',
            )
        }),
        ("Timestamps", {
            'fields': (
                'created_at',
                'updated_at',
            )
        }),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'amount',
        'currency',
        'status',
        'stripe_payment_intent_id',
        'stripe_invoice_id',
        'created_at',
    )
    list_filter = (
        'status',
        'currency',
        'created_at',
    )
    search_fields = (
        'user__username',
        'user__email',
        'stripe_payment_intent_id',
        'stripe_invoice_id',
    )
    readonly_fields = (
        'created_at',
    )
    ordering = ('-created_at',)


@admin.register(Usage)
class UsageAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'feature',
        'count',
        'period_start',
        'period_end',
        'created_at',
    )
    list_filter = (
        'feature',
        'period_start',
        'period_end',
    )
    search_fields = (
        'user__username',
        'user__email',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
    ordering = ('-created_at',)