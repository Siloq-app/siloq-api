"""
Agency & White-Label models.
Spec: Siloq White-Label Spec V1 (March 2026)
"""
from django.db import models


class AgencyProfile(models.Model):
    WHITE_LABEL_TIER_CHOICES = [
        ('PARTIAL', 'Agency - Powered by Siloq'),
        ('FULL',    'Agency Pro - Full Rebrand'),
    ]

    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='agency_profile',
    )
    agency_name  = models.CharField(max_length=255)
    agency_slug  = models.SlugField(unique=True)   # {slug}.app.siloq.ai
    white_label_tier = models.CharField(max_length=50, choices=WHITE_LABEL_TIER_CHOICES)
    max_sites    = models.IntegerField(default=10)  # 1 seat = 1 client site

    # Display Identity (Layer 2) — agency-controlled cosmetics
    logo_url       = models.URLField(blank=True, null=True, max_length=2048)
    logo_small_url = models.URLField(blank=True, null=True, max_length=2048)
    favicon_url    = models.URLField(blank=True, null=True, max_length=2048)
    color_primary   = models.CharField(max_length=7, default='#1A1A2E')
    color_secondary = models.CharField(max_length=7, default='#E8D48B')
    color_accent    = models.CharField(max_length=7, default='#4ADE80')
    support_email  = models.EmailField(blank=True, null=True)
    support_url    = models.URLField(blank=True, null=True)

    # Domain Identity (Agency Pro only)
    custom_domain      = models.CharField(max_length=255, blank=True, null=True, unique=True)
    domain_verified    = models.BooleanField(default=False)
    domain_verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'agency_profiles'

    def __str__(self):
        return self.agency_name

    @property
    def sites_used(self):
        return self.client_sites.filter(is_active=True).count()

    @property
    def sites_remaining(self):
        return self.max_sites - self.sites_used

    @property
    def show_powered_by(self):
        return self.white_label_tier != 'FULL'


class AgencyClientSite(models.Model):
    """
    Links an agency to each client site it manages.
    1 site = 1 client seat. Each site belongs to one agency.
    """
    agency      = models.ForeignKey(
        AgencyProfile,
        on_delete=models.CASCADE,
        related_name='client_sites',
    )
    site        = models.OneToOneField(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='agency_link',
    )
    client_user = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='agency_sites',
    )  # client who can view this site (optional)
    added_at  = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'agency_client_sites'
        constraints = [
            models.UniqueConstraint(fields=['agency', 'site'], name='unique_agency_site'),
        ]

    def __str__(self):
        return f"{self.agency} → {self.site}"


# ── Permission scoping utility ─────────────────────────────────────────────────

def get_visible_sites(user):
    """
    Returns the correct Site queryset based on user type.
    Agency owner → all their active client sites.
    Client user  → only sites assigned to them.
    Standard     → their own sites.
    """
    from sites.models import Site

    if hasattr(user, 'agency_profile'):
        return Site.objects.filter(
            agency_link__agency=user.agency_profile,
            agency_link__is_active=True,
        )

    if user.agency_sites.exists():
        return Site.objects.filter(
            agency_link__client_user=user,
            agency_link__is_active=True,
        )

    return user.sites.all()


def can_add_site(agency_profile):
    return agency_profile.sites_used < agency_profile.max_sites
