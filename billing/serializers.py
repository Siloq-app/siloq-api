"""
Serializers for billing and subscription models.
"""
from rest_framework import serializers
from .models import Subscription, Payment


class SubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for Subscription model."""
    is_trial_active = serializers.BooleanField(read_only=True)
    trial_days_remaining = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Subscription
        fields = (
            'id', 'tier', 'status', 'stripe_customer_id',
            'trial_started_at', 'trial_ends_at', 'trial_pages_limit', 'trial_pages_used',
            'is_trial_active', 'trial_days_remaining',
            'current_period_start', 'current_period_end',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model."""
    
    class Meta:
        model = Payment
        fields = (
            'id', 'stripe_payment_intent_id', 'stripe_invoice_id',
            'amount', 'currency', 'status', 'description', 'created_at'
        )
        read_only_fields = ('id', 'created_at')


class CheckoutSessionSerializer(serializers.Serializer):
    """Serializer for creating Stripe checkout sessions."""
    tier = serializers.ChoiceField(
        choices=[
            ('pro', 'Pro'),
            ('builder_plus', 'Builder Plus'),
            ('architect', 'Architect'),
            ('empire', 'Empire'),
        ]
    )
    success_url = serializers.URLField()
    cancel_url = serializers.URLField()


class PortalSessionSerializer(serializers.Serializer):
    """Serializer for creating Stripe customer portal sessions."""
    return_url = serializers.URLField()
