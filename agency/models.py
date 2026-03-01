from django.db import models


class AgencyProfile(models.Model):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='agency_profile',
    )
    agency_name = models.CharField(max_length=255)
    agency_slug = models.SlugField(max_length=100, unique=True)

    WHITE_LABEL_TIER_CHOICES = [
        ('NO_WHITE_LABEL', 'No White Label'),
        ('PARTIAL_WHITE_LABEL', 'Partial (Agency)'),
        ('FULL_WHITE_LABEL', 'Full (Empire)'),
    ]
    white_label_tier = models.CharField(
        max_length=50,
        default='NO_WHITE_LABEL',
        choices=WHITE_LABEL_TIER_CHOICES,
    )

    # Branding
    logo_url = models.URLField(blank=True, max_length=2048)
    logo_small_url = models.URLField(blank=True, max_length=2048)
    favicon_url = models.URLField(blank=True, max_length=2048)
    color_primary = models.CharField(max_length=7, default='#E8D48B')
    color_secondary = models.CharField(max_length=7, default='#C8A951')
    color_accent = models.CharField(max_length=7, default='#3B82F6')
    color_background = models.CharField(max_length=7, default='#1A1A2E')
    color_text = models.CharField(max_length=7, default='#F8F8F8')

    # Identity
    support_email = models.EmailField(blank=True)
    support_url = models.URLField(blank=True)
    tagline = models.CharField(max_length=255, blank=True)

    # Domain (Empire only)
    custom_domain = models.CharField(max_length=255, blank=True)
    domain_verified = models.BooleanField(default=False)
    domain_verified_at = models.DateTimeField(null=True, blank=True)

    # Powered-by attribution
    show_powered_by = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agency_profiles'

    def __str__(self):
        return self.agency_name


class AgencyClientLink(models.Model):
    agency = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='agency_clients',
    )
    client = models.ForeignKey(  # null=True for pending invites
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='agency_memberships',
        null=True,
        blank=True,
    )

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('invited', 'Invited'),
        ('suspended', 'Suspended'),
    ]
    status = models.CharField(max_length=20, default='active', choices=STATUS_CHOICES)
    invite_email = models.EmailField(blank=True)
    invite_token = models.CharField(max_length=64, blank=True, unique=True, null=True)
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'agency_client_links'
        unique_together = [('agency', 'client')]

    def __str__(self):
        return f"{self.agency} -> {self.client} ({self.status})"
