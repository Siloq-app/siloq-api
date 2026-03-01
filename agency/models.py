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
        ('PARTIAL', 'Agency - Powered by Siloq'),
        ('FULL', 'Agency Pro - Full Rebrand'),
    ]
    white_label_tier = models.CharField(
        max_length=50,
        choices=WHITE_LABEL_TIER_CHOICES,
    )
    max_client_seats = models.IntegerField(default=10)

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
        AgencyProfile,
        on_delete=models.CASCADE,
        related_name='clients',
    )
    client_user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='agency_link',
        null=True,
        blank=True,
    )
    sites = models.ManyToManyField('sites.Site', blank=True)
    invite_email = models.EmailField(blank=True)
    invite_token = models.CharField(max_length=64, blank=True, unique=True, null=True)
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'agency_client_links'

    def __str__(self):
        return f"{self.agency} -> {self.client_user or self.invite_email}"


def get_visible_sites(user):
    """
    Returns the correct Site queryset for any user type.
    Agency sees all client sites. Client sees assigned sites. Standard sees own.
    """
    from sites.models import Site
    if hasattr(user, 'agency_profile'):
        return Site.objects.filter(
            agencyclientlink__agency=user.agency_profile
        ).distinct()
    if hasattr(user, 'agency_link'):
        return user.agency_link.sites.all()
    return Site.objects.filter(user=user)
