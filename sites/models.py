"""
Site and API Key models.
"""
import secrets
import hashlib
from django.db import models
from django.conf import settings
from django.utils import timezone


class Site(models.Model):
    """
    Represents a WordPress website connected to Siloq.
    One user can have multiple sites.
    """
    # Business type choices
    BUSINESS_TYPE_CHOICES = [
        ('local_service', 'Local/Service Business'),
        ('ecommerce', 'E-Commerce'),
        ('content_blog', 'Content/Blog'),
        ('saas', 'SaaS/Software'),
        ('other', 'Other'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sites'
    )
    name = models.CharField(max_length=255)
    url = models.URLField(help_text="Base URL of the WordPress site")
    wp_site_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="WordPress site identifier"
    )
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_requested_at = models.DateTimeField(null=True, blank=True, help_text="When user requested a sync from dashboard")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Business Profile (Onboarding Wizard)
    business_type = models.CharField(
        max_length=50,
        choices=BUSINESS_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Type of business"
    )
    primary_services = models.JSONField(
        default=list,
        blank=True,
        help_text="List of main services/products the business offers"
    )
    service_areas = models.JSONField(
        default=list,
        blank=True,
        help_text="List of geographic areas served (for local businesses)"
    )
    target_audience = models.TextField(
        blank=True,
        help_text="Description of target audience/customers"
    )
    business_description = models.TextField(
        blank=True,
        help_text="Brief description of the business"
    )
    onboarding_complete = models.BooleanField(
        default=False,
        help_text="Whether the business onboarding wizard has been completed"
    )
    
    # Google Search Console Integration
    gsc_site_url = models.URLField(
        blank=True,
        null=True,
        help_text="GSC property URL (e.g., https://example.com/)"
    )
    gsc_access_token = models.TextField(
        blank=True,
        null=True,
        help_text="GSC OAuth access token"
    )
    gsc_refresh_token = models.TextField(
        blank=True,
        null=True,
        help_text="GSC OAuth refresh token"
    )
    gsc_token_expires_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the access token expires"
    )
    gsc_connected_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When GSC was connected"
    )

    class Meta:
        db_table = 'sites'
        ordering = ['-created_at']
        unique_together = [['user', 'url']]

    def __str__(self):
        return f"{self.name} ({self.url})"
    
    @property
    def needs_onboarding(self):
        """Check if site needs to complete onboarding."""
        return not self.onboarding_complete


class APIKey(models.Model):
    """
    API Key for authenticating WordPress plugin requests.
    Keys are hashed before storage and prefixed with 'sk_siloq_'.
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='api_keys'
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable name for the API key"
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 hash of the API key"
    )
    key_prefix = models.CharField(
        max_length=20,
        help_text="First 16 characters of the key for display"
    )
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    usage_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'api_keys'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...)"

    @staticmethod
    def generate_key():
        """
        Generate a new API key.
        Returns: (full_key, prefix, hash)
        """
        prefix = 'sk_siloq'
        random_part = secrets.token_urlsafe(32)
        full_key = f"{prefix}_{random_part}"
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()
        key_prefix = full_key[:16] + '...'
        
        return full_key, key_prefix, key_hash

    @staticmethod
    def hash_key(key):
        """Hash an API key for comparison."""
        return hashlib.sha256(key.encode()).hexdigest()

    def verify_key(self, key):
        """Verify if a provided key matches this API key."""
        return self.key_hash == self.hash_key(key) and self.is_active

    def revoke(self):
        """Revoke this API key."""
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save()

    def mark_used(self):
        """Mark this key as used (update last_used_at and increment usage_count)."""
        self.last_used_at = timezone.now()
        self.usage_count += 1
        self.save(update_fields=['last_used_at', 'usage_count'])


class AccountKey(models.Model):
    """
    Master/Agency API Key for authenticating across multiple sites.
    Linked to user account, not a specific site.
    Keys are prefixed with 'ak_siloq_' (account key).
    
    When used:
    - Validates against user account
    - Auto-creates sites on first sync if they don't exist
    - Allows unlimited site management with single key
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='account_keys'
    )
    name = models.CharField(
        max_length=255,
        help_text="Human-readable name for the API key"
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 hash of the API key"
    )
    key_prefix = models.CharField(
        max_length=20,
        help_text="First 16 characters of the key for display"
    )
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    usage_count = models.IntegerField(default=0)
    sites_created = models.IntegerField(default=0, help_text="Number of sites auto-created with this key")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'account_keys'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.key_prefix}...) - {self.user.email}"

    @staticmethod
    def generate_key():
        """
        Generate a new Account API key.
        Returns: (full_key, prefix, hash)
        """
        prefix = 'ak_siloq'  # 'ak' for account key (vs 'sk' for site key)
        random_part = secrets.token_urlsafe(32)
        full_key = f"{prefix}_{random_part}"
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()
        key_prefix = full_key[:16] + '...'
        
        return full_key, key_prefix, key_hash

    @staticmethod
    def hash_key(key):
        """Hash an API key for comparison."""
        return hashlib.sha256(key.encode()).hexdigest()

    def verify_key(self, key):
        """Verify if a provided key matches this API key."""
        return self.key_hash == self.hash_key(key) and self.is_active

    def revoke(self):
        """Revoke this API key."""
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save()

    def mark_used(self):
        """Mark this key as used (update last_used_at and increment usage_count)."""
        self.last_used_at = timezone.now()
        self.usage_count += 1
        self.save(update_fields=['last_used_at', 'usage_count'])
    
    def increment_sites_created(self):
        """Increment the sites_created counter."""
        self.sites_created += 1
        self.save(update_fields=['sites_created'])
