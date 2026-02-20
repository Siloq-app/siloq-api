"""
Serializers for Site, APIKey, and AccountKey models.
"""
from rest_framework import serializers
from .models import Site, APIKey, AccountKey


class SiteSerializer(serializers.ModelSerializer):
    """Serializer for Site model."""
    page_count = serializers.SerializerMethodField()
    api_key_count = serializers.SerializerMethodField()
    gsc_connected = serializers.SerializerMethodField()
    needs_onboarding = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Site
        fields = (
            'id', 'name', 'url', 'wp_site_id', 'is_active',
            'last_synced_at', 'sync_requested_at', 'created_at', 'updated_at',
            'page_count', 'api_key_count', 'gsc_connected',
            # Business profile fields
            'business_type', 'primary_services', 'service_areas',
            'target_audience', 'business_description', 'onboarding_complete',
            'needs_onboarding'
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'last_synced_at', 'sync_requested_at', 'needs_onboarding')

    def get_gsc_connected(self, obj):
        """Check if GSC is connected (has refresh token)."""
        return bool(getattr(obj, 'gsc_refresh_token', None))

    def get_page_count(self, obj):
        """Get count of pages for this site."""
        return obj.pages.count()

    def get_api_key_count(self, obj):
        """Get count of active API keys for this site."""
        return obj.api_keys.filter(is_active=True).count()


class BusinessProfileSerializer(serializers.ModelSerializer):
    """Serializer for business profile (onboarding wizard)."""
    
    class Meta:
        model = Site
        fields = (
            'business_type',
            'primary_services',
            'service_areas',
            'target_audience',
            'business_description',
            'onboarding_complete',
        )
    
    def validate_primary_services(self, value):
        """Ensure primary_services is a list of strings."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of services")
        if len(value) > 20:
            raise serializers.ValidationError("Maximum 20 services allowed")
        return [str(s).strip() for s in value if s]
    
    def validate_service_areas(self, value):
        """Ensure service_areas is a list of strings."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of areas")
        if len(value) > 50:
            raise serializers.ValidationError("Maximum 50 service areas allowed")
        return [str(a).strip() for a in value if a]
    
    def update(self, instance, validated_data):
        """Update profile and mark onboarding as complete if all required fields filled."""
        instance = super().update(instance, validated_data)
        
        # Auto-mark onboarding complete if business_type and primary_services are set
        if instance.business_type and instance.primary_services:
            instance.onboarding_complete = True
            instance.save(update_fields=['onboarding_complete'])
        
        return instance


class APIKeySerializer(serializers.ModelSerializer):
    """Serializer for APIKey model (safe - doesn't expose full key)."""
    
    class Meta:
        model = APIKey
        fields = (
            'id', 'site', 'name', 'key_prefix', 'is_active',
            'created_at', 'last_used_at', 'usage_count'
        )
        read_only_fields = ('id', 'site', 'key_prefix', 'created_at', 'last_used_at', 'usage_count')


class APIKeyCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating APIKey (includes full key in response)."""
    key = serializers.CharField(read_only=True, help_text="Full API key (shown only once)")
    
    class Meta:
        model = APIKey
        fields = ('id', 'name', 'key', 'key_prefix', 'created_at', 'is_active')
        read_only_fields = ('id', 'key', 'key_prefix', 'created_at', 'is_active')


class AccountKeySerializer(serializers.ModelSerializer):
    """Serializer for AccountKey model (safe - doesn't expose full key)."""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = AccountKey
        fields = (
            'id', 'name', 'key_prefix', 'is_active',
            'created_at', 'last_used_at', 'usage_count',
            'sites_created', 'user_email'
        )
        read_only_fields = (
            'id', 'key_prefix', 'created_at', 'last_used_at',
            'usage_count', 'sites_created', 'user_email'
        )


class AccountKeyCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating AccountKey (includes full key in response)."""
    key = serializers.CharField(read_only=True, help_text="Full API key (shown only once)")
    
    class Meta:
        model = AccountKey
        fields = ('id', 'name', 'key', 'key_prefix', 'created_at', 'is_active', 'sites_created')
        read_only_fields = ('id', 'key', 'key_prefix', 'created_at', 'is_active', 'sites_created')
