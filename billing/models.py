"""
Billing and AI usage models.
Handles trial tracking, AI billing modes, usage logging, and Stripe integration.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


class ProjectAISettings(models.Model):
    """
    AI billing configuration per project/site.
    Tracks billing mode, API keys, and trial usage.
    """
    MODE_CHOICES = [
        ('trial', 'Free Trial'),
        ('byok', 'Bring Your Own Key'),
        ('siloq_managed', 'Siloq-Managed Billing'),
    ]
    
    PROVIDER_CHOICES = [
        ('openai', 'OpenAI'),
        ('gemini', 'Google Gemini'),
        ('anthropic', 'Anthropic'),
    ]
    
    # Link to site (one-to-one)
    site = models.OneToOneField(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='ai_settings'
    )
    
    # AI Provider configuration
    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        default='openai'
    )
    
    # Billing mode
    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default='trial'
    )
    
    # BYOK: Encrypted API key (stored securely)
    api_key_encrypted = models.TextField(
        null=True,
        blank=True,
        help_text="Encrypted API key for BYOK mode"
    )
    
    # Siloq-Managed: Stripe customer reference
    stripe_customer_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Stripe customer ID for managed billing"
    )
    
    # Billing enabled flag
    billing_enabled = models.BooleanField(
        default=False,
        help_text="Whether billing is properly configured"
    )
    
    # Trial tracking
    trial_pages_used = models.IntegerField(
        default=0,
        help_text="Number of pages generated during trial"
    )
    trial_pages_limit = models.IntegerField(
        default=10,
        help_text="Maximum pages allowed in trial (default: 10)"
    )
    trial_start_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the trial started"
    )
    trial_end_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the trial expires"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'project_ai_settings'
        verbose_name = 'Project AI Settings'
        verbose_name_plural = 'Project AI Settings'

    def __str__(self):
        return f"{self.site.name} - {self.get_mode_display()}"

    def start_trial(self):
        """Initialize trial period."""
        self.mode = 'trial'
        self.trial_start_date = timezone.now()
        self.trial_end_date = timezone.now() + timedelta(days=10)
        self.trial_pages_used = 0
        self.save()

    @property
    def is_trial_active(self):
        """Check if trial is still valid."""
        if self.mode != 'trial':
            return False
        if not self.trial_end_date:
            return False
        return timezone.now() < self.trial_end_date

    @property
    def trial_pages_remaining(self):
        """Pages remaining in trial."""
        return max(0, self.trial_pages_limit - self.trial_pages_used)

    @property
    def is_trial_exhausted(self):
        """Check if trial page limit reached."""
        return self.trial_pages_used >= self.trial_pages_limit


class AIUsageLog(models.Model):
    """
    Tracks AI usage and costs for billing transparency.
    Every AI execution is logged here.
    """
    # Link to site
    site = models.ForeignKey(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='ai_usage_logs'
    )
    
    # Optional link to content job
    content_job_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Reference to the content generation job"
    )
    
    # Provider details
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=100)
    
    # Token usage
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    
    # Cost breakdown (in USD)
    provider_cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text="Raw cost from AI provider"
    )
    siloq_fee_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text="Siloq fee (5% for managed billing, 0 for BYOK)"
    )
    total_charge_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        default=0,
        help_text="Total charge = provider_cost + siloq_fee"
    )
    
    # Trial flag
    is_trial = models.BooleanField(
        default=False,
        help_text="Whether this usage was during trial (Siloq absorbs cost)"
    )
    
    # Billing mode at time of execution
    billing_mode = models.CharField(
        max_length=20,
        default='trial'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_usage_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['site', 'created_at']),
            models.Index(fields=['content_job_id']),
        ]

    def __str__(self):
        return f"{self.site.name} - {self.model} - ${self.total_charge_usd}"


class BillingEvent(models.Model):
    """
    Tracks Stripe billing events for Siloq-Managed billing.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('captured', 'Captured'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]
    
    # Link to site
    site = models.ForeignKey(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='billing_events'
    )
    
    # Link to usage log
    ai_usage_log = models.ForeignKey(
        AIUsageLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='billing_events'
    )
    
    # Stripe references
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )
    stripe_charge_id = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )
    
    # Amount
    amount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Error tracking
    error_message = models.TextField(
        null=True,
        blank=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_events'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.site.name} - ${self.amount_usd} - {self.status}"
