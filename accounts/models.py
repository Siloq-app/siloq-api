"""
User account models.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta


class User(AbstractUser):
    """
    Custom User model extending Django's AbstractUser.
    Used for dashboard user authentication.
    """
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Stripe integration
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_tier = models.CharField(
        max_length=50, 
        blank=True, 
        null=True,
        choices=[
            ('pro', 'Pro'),
            ('builder', 'Builder+'),
            ('architect', 'Architect'),
            ('empire', 'Empire'),
        ]
    )
    subscription_status = models.CharField(
        max_length=50,
        default='inactive',
        choices=[
            ('inactive', 'Inactive'),
            ('trial', 'Trial'),
            ('active', 'Active'),
            ('past_due', 'Past Due'),
            ('canceled', 'Canceled'),
        ]
    )
    
    # Free trial (10 days, no credit card)
    trial_started_at = models.DateTimeField(blank=True, null=True)
    trial_ends_at = models.DateTimeField(blank=True, null=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']

    def __str__(self):
        return self.email
    
    def start_trial(self):
        """Start the 10-day free trial."""
        self.trial_started_at = timezone.now()
        self.trial_ends_at = timezone.now() + timedelta(days=10)
        self.subscription_status = 'trial'
        self.save(update_fields=['trial_started_at', 'trial_ends_at', 'subscription_status'])
    
    def is_trial_active(self):
        """Check if user is in active trial period."""
        if self.subscription_status != 'trial':
            return False
        if not self.trial_ends_at:
            return False
        return timezone.now() < self.trial_ends_at
    
    def trial_days_remaining(self):
        """Get number of days remaining in trial."""
        if not self.trial_ends_at:
            return 0
        delta = self.trial_ends_at - timezone.now()
        return max(0, delta.days)
    
    def has_active_subscription(self):
        """Check if user has an active paid subscription or trial."""
        if self.is_trial_active():
            return True
        return self.subscription_status == 'active'
    
    def get_tier_limits(self):
        """Get limits based on subscription tier."""
        TIER_LIMITS = {
            'trial': {'sites': 1, 'silos': 1, 'pages': 10},
            'pro': {'sites': 1, 'silos': 2, 'pages': None},
            'builder': {'sites': 1, 'silos': None, 'pages': None},
            'architect': {'sites': 5, 'silos': None, 'pages': None},
            'empire': {'sites': 20, 'silos': None, 'pages': None},
        }
        
        if self.is_trial_active():
            return TIER_LIMITS['trial']
        
        return TIER_LIMITS.get(self.subscription_tier, TIER_LIMITS['trial'])
