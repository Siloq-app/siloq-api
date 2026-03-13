"""
Billing and subscription models.
Handles Stripe subscriptions, payments, and user billing information.
"""
from django.db import models
from django.conf import settings
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
        settings.AUTH_USER_MODEL,
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
        settings.AUTH_USER_MODEL,
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
        settings.AUTH_USER_MODEL,
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


class SiteCredits(models.Model):
    """
    Tracks AI action credits per site (not per user — agencies manage per site).
    """
    site = models.OneToOneField(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="credits"
    )
    plan_tier = models.CharField(max_length=20, default="free_trial")
    monthly_allowance = models.IntegerField(default=0)
    current_balance = models.IntegerField(default=0)
    lifetime_used = models.IntegerField(default=0)
    reset_date = models.DateField(null=True, blank=True)
    is_trial = models.BooleanField(default=True)
    trial_actions_remaining = models.IntegerField(default=25)  # Only used when is_trial=True
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_site_credits"
        verbose_name = "Site Credits"
        verbose_name_plural = "Site Credits"

    def __str__(self):
        return f"{self.site} — {self.current_balance} credits remaining"

    @property
    def effective_balance(self):
        """Returns the usable balance based on account type."""
        if self.is_trial:
            return self.trial_actions_remaining
        return self.current_balance

    def can_use(self, cost=1):
        """Check if site has enough credits for an action."""
        return self.effective_balance >= cost

    def deduct(self, cost=1, action_type=""):
        """Deduct credits and record usage. Returns True if successful."""
        if not self.can_use(cost):
            return False
        if self.is_trial:
            self.trial_actions_remaining = max(0, self.trial_actions_remaining - cost)
        else:
            self.current_balance = max(0, self.current_balance - cost)
        self.lifetime_used += cost
        self.save(update_fields=["trial_actions_remaining", "current_balance", "lifetime_used", "updated_at"])
        CreditTransaction.objects.create(
            site_credits=self,
            action_type=action_type,
            cost=cost,
        )
        return True

    def reset_monthly(self):
        """Called on billing anniversary. Adds monthly_allowance respecting rollover cap."""
        from datetime import date
        from dateutil.relativedelta import relativedelta
        if self.is_trial:
            return  # Trial accounts never reset
        rollover_cap = self.monthly_allowance  # Max 1 month rollover
        new_balance = min(self.current_balance + self.monthly_allowance, self.monthly_allowance + rollover_cap)
        self.current_balance = new_balance
        self.reset_date = date.today() + relativedelta(months=1)
        self.save(update_fields=["current_balance", "reset_date", "updated_at"])


class CreditTransaction(models.Model):
    ACTION_CHOICES = [
        ("auto_add_link", "Auto-Add Internal Link"),
        ("schema_generation", "Schema Generation"),
        ("content_draft", "Content Draft"),
        ("widget_intelligence", "Widget Intelligence"),
        ("bulk_operation", "Bulk Site Operation"),
        ("content_engine", "Content Engine Run"),
        ("site_audit", "Site Audit"),
        ("cannibalization_analysis", "Cannibalization Analysis"),
        ("manual_adjustment", "Manual Adjustment"),
        ("purchase", "Credit Purchase"),
    ]

    site_credits = models.ForeignKey(
        SiteCredits,
        on_delete=models.CASCADE,
        related_name="transactions"
    )
    action_type = models.CharField(max_length=50, choices=ACTION_CHOICES, default="manual_adjustment")
    cost = models.IntegerField(default=1)  # Positive = debit, negative = credit
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_credit_transactions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.site_credits.site} — {self.action_type} ({self.cost})"


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------
from django.db.models.signals import post_save
from django.dispatch import receiver

PLAN_ALLOWANCES = {
    "free_trial": 0,   # trial uses trial_actions_remaining
    "pro": 200,
    "builder_plus": 500,
    "architect": 500,
    "empire": 500,
}


@receiver(post_save, sender="sites.Site")
def create_site_credits(sender, instance, created, **kwargs):
    """Auto-create SiteCredits when a new Site is created."""
    if created:
        from datetime import date
        from dateutil.relativedelta import relativedelta
        tier = "free_trial"
        try:
            tier = instance.user.subscription.tier
        except Exception:
            pass
        is_trial = tier == "free_trial"
        allowance = PLAN_ALLOWANCES.get(tier, 0)
        SiteCredits.objects.get_or_create(
            site=instance,
            defaults={
                "plan_tier": tier,
                "monthly_allowance": allowance,
                "current_balance": allowance,
                "is_trial": is_trial,
                "trial_actions_remaining": 25 if is_trial else 0,
                "reset_date": date.today() + relativedelta(months=1) if not is_trial else None,
            }
        )


@receiver(post_save, sender=Subscription)
def update_site_credits_on_tier_change(sender, instance, **kwargs):
    """When subscription tier changes, update all SiteCredits for that user."""
    from datetime import date
    from dateutil.relativedelta import relativedelta
    tier = instance.tier
    is_trial = tier == "free_trial"
    allowance = PLAN_ALLOWANCES.get(tier, 0)
    for sc in SiteCredits.objects.filter(site__user=instance.user):
        sc.plan_tier = tier
        sc.monthly_allowance = allowance
        sc.is_trial = is_trial
        if not is_trial and sc.current_balance == 0:
            # Give initial balance on upgrade
            sc.current_balance = allowance
            sc.reset_date = date.today() + relativedelta(months=1)
        sc.save()
