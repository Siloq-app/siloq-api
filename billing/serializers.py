"""
Serializers for billing models.
"""
from rest_framework import serializers
from .models import ProjectAISettings, AIUsageLog, BillingEvent


class ProjectAISettingsSerializer(serializers.ModelSerializer):
    """AI settings serializer (excludes sensitive data)."""
    is_trial_active = serializers.BooleanField(read_only=True)
    trial_pages_remaining = serializers.IntegerField(read_only=True)
    is_trial_exhausted = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = ProjectAISettings
        fields = [
            'id', 'provider', 'mode', 'billing_enabled',
            'trial_pages_used', 'trial_pages_limit',
            'trial_start_date', 'trial_end_date',
            'is_trial_active', 'trial_pages_remaining', 'is_trial_exhausted',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['trial_pages_used', 'trial_start_date', 'trial_end_date']


class ProjectAISettingsUpdateSerializer(serializers.ModelSerializer):
    """For updating AI settings (mode change, API key)."""
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = ProjectAISettings
        fields = ['mode', 'provider', 'api_key']
    
    def update(self, instance, validated_data):
        api_key = validated_data.pop('api_key', None)
        if api_key:
            # In production, encrypt this before storing
            instance.api_key_encrypted = api_key  # TODO: Add encryption
        return super().update(instance, validated_data)


class AIUsageLogSerializer(serializers.ModelSerializer):
    """AI usage log serializer."""
    class Meta:
        model = AIUsageLog
        fields = [
            'id', 'content_job_id', 'provider', 'model',
            'input_tokens', 'output_tokens',
            'provider_cost_usd', 'siloq_fee_usd', 'total_charge_usd',
            'is_trial', 'billing_mode', 'created_at'
        ]


class BillingEventSerializer(serializers.ModelSerializer):
    """Billing event serializer."""
    class Meta:
        model = BillingEvent
        fields = [
            'id', 'stripe_payment_intent_id', 'amount_usd',
            'status', 'error_message', 'created_at'
        ]


class CostEstimateSerializer(serializers.Serializer):
    """Cost estimate before AI execution."""
    allowed = serializers.BooleanField()
    error_code = serializers.CharField(allow_null=True)
    error_message = serializers.CharField(allow_null=True)
    warning = serializers.CharField(allow_null=True)
    estimated_input_tokens = serializers.IntegerField()
    estimated_output_tokens = serializers.IntegerField()
    estimated_provider_cost_usd = serializers.DecimalField(max_digits=10, decimal_places=6)
    estimated_siloq_fee_usd = serializers.DecimalField(max_digits=10, decimal_places=6)
    estimated_total_cost_usd = serializers.DecimalField(max_digits=10, decimal_places=6)
