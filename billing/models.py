"""
Billing and subscription models.
Handles Stripe subscriptions, payments, and user billing information.
"""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Subscription(models.Model):
    """
    User subscription information linked to Stripe.
    """
    TIER_CHOICES = [
        ('free_trial', 'Free Trial'),
        ('pro', 'Pro'),
        ('builder_plus', 'Builder Plus'),
        ('architect', 'Architect'),
        ('empire', 'Empire'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('canceled', 'Canceled'),
        ('past_due', 'Past Due'),
        ('trialing', 'Trialing'),
        ('incomplete', 'Incomplete'),
    ]
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    
    tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        default='free_trial'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='trialing'
    )
    
    # Trial information
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    trial_pages_limit = models.IntegerField(default=10)
    trial_pages_used = models.IntegerField(default=0)
    
    # Billing cycle
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'subscriptions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.tier} ({self.status})"
    
    @property
    def is_trial_active(self):
        """Check if the trial period is still active."""
        if not self.trial_ends_at:
            return False
        return timezone.now() < self.trial_ends_at
    
    @property
    def trial_days_remaining(self):
        """Calculate remaining trial days."""
        if not self.is_trial_active:
            return 0
        delta = self.trial_ends_at - timezone.now()
        return max(0, delta.days)


class Payment(models.Model):
    """
    Individual payment records.
    """
    STATUS_CHOICES = [
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
        ('refunded', 'Refunded'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    stripe_payment_intent_id = models.CharField(max_length=255)
    stripe_invoice_id = models.CharField(max_length=255, blank=True)
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='usd')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    
    description = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'payments'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - ${self.amount} ({self.status})"


class Usage(models.Model):
    """
    Track feature usage for billing and trial limits.
    """
    FEATURE_CHOICES = [
        ('pages', 'Pages Analyzed'),
        ('scans', 'SEO Scans'),
        ('cannibalization', 'Cannibalization Analysis'),
        ('silo_analysis', 'Silo Analysis'),
        ('api_calls', 'API Calls'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='usage_records'
    )
    feature = models.CharField(max_length=30, choices=FEATURE_CHOICES)
    count = models.PositiveIntegerField(default=0)
    
    # Billing period tracking
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'usage'
        ordering = ['-created_at']
        unique_together = ['user', 'feature', 'period_start']
    
    def __str__(self):
        return f"{self.user.username} - {self.feature}: {self.count}"
