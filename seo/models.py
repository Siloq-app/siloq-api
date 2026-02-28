"""
SEO models — Page/Link analysis (v1) + Anti-Cannibalization Engine (v2).

v2 tables are organised into five domains:
  1. Core Registry        — SiloDefinition, SiloKeyword, KeywordAssignment, KeywordAssignmentHistory, PageMetadata
  2. Detection & Conflicts — CannibalizationConflict, ConflictPage, ConflictResolution
  3. Content Lifecycle     — ContentHealthScore, FreshnessAlert, LifecycleQueue, ContentAuditLog
  4. Redirect Management   — RedirectRegistry
  5. Validation & Preflight — ValidationLog
"""

import json
import uuid
from django.db import models
from sites.models import Site


class SafeJSONField(models.JSONField):
    """
    JSONField that handles psycopg2 2.9 + Django 5 double-decode issue.

    Django 5 registers custom JSON adapters for JSONB (OID 3802) columns only.
    Plain JSON (OID 114) columns are auto-decoded by psycopg2 to Python objects,
    then Django's from_db_value calls json.loads() on the already-decoded value
    → TypeError. This subclass adds the isinstance(str) guard.

    Use for any JSONField backed by a plain JSON (not JSONB) DB column, or as a
    general-purpose safe replacement when managed=False.
    """
    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        if isinstance(value, str):
            return json.loads(value, cls=self.decoder)
        return value  # Already decoded by psycopg2 (json OID 114 without Django adapter)


# ─────────────────────────────────────────────────────────────
# V1 MODELS (existing)
# ─────────────────────────────────────────────────────────────

class Page(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='pages')
    wp_post_id = models.IntegerField(help_text="WordPress post/page ID")
    url = models.URLField()
    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500)
    content = models.TextField(blank=True)
    excerpt = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='publish', choices=[
        ('publish', 'Published'), ('draft', 'Draft'), ('private', 'Private'),
    ])
    post_type = models.CharField(max_length=50, default='page',
        help_text="WordPress post type: page, post, product, product_cat")
    published_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    parent_id = models.IntegerField(null=True, blank=True)
    menu_order = models.IntegerField(default=0)

    yoast_title = models.CharField(max_length=500, blank=True)
    yoast_description = models.TextField(blank=True)
    featured_image = models.URLField(blank=True)

    siloq_page_id = models.CharField(max_length=255, blank=True, null=True)
    is_money_page = models.BooleanField(default=False)
    is_homepage = models.BooleanField(default=False)
    is_noindex = models.BooleanField(default=False)

    PAGE_TYPE_CHOICES = [
        ('money', 'Money Page'),
        ('supporting', 'Supporting Content'),
        ('utility', 'Utility Page'),
        ('conversion', 'Conversion Page'),
        ('archive', 'Archive / Index'),
        ('product', 'E-commerce Product'),
    ]
    page_type_classification = models.CharField(
        max_length=20, default='supporting', choices=PAGE_TYPE_CHOICES,
        help_text="6-type page classification",
    )
    page_type_override = models.BooleanField(
        default=False,
        help_text="True if user manually set the page type (skip auto-reclassification)",
    )

    PAGE_BUILDER_CHOICES = [
        ('standard',     'Standard WordPress'),
        ('gutenberg',    'Gutenberg Block Editor'),
        ('elementor',    'Elementor'),
        ('cornerstone',  'Cornerstone / X Theme'),
        ('divi',         'Divi'),
        ('wpbakery',     'WPBakery'),
        ('beaver_builder', 'Beaver Builder'),
        ('unknown',      'Unknown'),
    ]
    page_builder = models.CharField(
        max_length=30,
        choices=PAGE_BUILDER_CHOICES,
        default='unknown',
        blank=True,
        help_text="Page builder detected during sync (elementor, cornerstone, divi, wpbakery, beaver_builder, gutenberg, standard)",
    )

    # Junk page detection (Section 04)
    JUNK_ACTION_CHOICES = [
        ('delete',  'Delete'),
        ('noindex', 'Noindex'),
        ('review',  'Needs Review'),
    ]
    junk_action = models.CharField(max_length=10, choices=JUNK_ACTION_CHOICES, blank=True, null=True,
        help_text="Recommended action from junk detector (delete/noindex/review)")
    junk_reason = models.CharField(max_length=200, blank=True, null=True,
        help_text="Why this page was flagged as junk")

    last_synced_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pages'
        ordering = ['-created_at']
        unique_together = [['site', 'wp_post_id']]
        indexes = [
            models.Index(fields=['site', 'status']),
            models.Index(fields=['url']),
            models.Index(fields=['is_money_page']),
            models.Index(fields=['is_homepage']),
            models.Index(fields=['page_type_classification']),
        ]

    def __str__(self):
        return f"{self.title} ({self.site.name})"

    @property
    def page_type(self):
        """Return the 6-type classification. Backward-compat wrapper."""
        return self.page_type_classification

    @page_type.setter
    def page_type(self, value):
        self.page_type_classification = value
        # Keep is_money_page in sync
        self.is_money_page = (value == 'money')


class InternalLink(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='internal_links')
    source_page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='outgoing_links')
    target_page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='incoming_links',
        null=True, blank=True)
    target_url = models.URLField()
    anchor_text = models.CharField(max_length=500, blank=True)
    anchor_text_normalized = models.CharField(max_length=500, blank=True)
    context_text = models.TextField(blank=True)
    is_in_content = models.BooleanField(default=True)
    is_nofollow = models.BooleanField(default=False)
    is_valid = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'internal_links'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['site', 'source_page']),
            models.Index(fields=['site', 'target_page']),
            models.Index(fields=['anchor_text_normalized']),
        ]

    def __str__(self):
        return f"{self.source_page.title} → {self.anchor_text} → {self.target_url}"

    def save(self, *args, **kwargs):
        if self.anchor_text:
            self.anchor_text_normalized = self.anchor_text.lower().strip()
        super().save(*args, **kwargs)


class AnchorTextConflict(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='anchor_conflicts')
    anchor_text = models.CharField(max_length=500)
    anchor_text_normalized = models.CharField(max_length=500)
    conflicting_pages = models.ManyToManyField(Page, related_name='anchor_conflicts')
    occurrence_count = models.IntegerField(default=0)
    severity = models.CharField(max_length=20, choices=[
        ('high', 'High'), ('medium', 'Medium'), ('low', 'Low'),
    ], default='medium')
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'anchor_text_conflicts'
        ordering = ['-severity', '-occurrence_count']

    def __str__(self):
        return f"Conflict: '{self.anchor_text}' → {self.conflicting_pages.count()} pages"


class LinkIssue(models.Model):
    ISSUE_TYPES = [
        ('anchor_conflict', 'Anchor Text Conflict'),
        ('homepage_theft', 'Homepage Anchor Theft'),
        ('missing_target_link', 'Missing Link to Target'),
        ('missing_sibling_links', 'Missing Sibling Links'),
        ('orphan_page', 'Orphan Page'),
        ('cross_silo_link', 'Cross-Silo Link'),
        ('too_many_supporting', 'Too Many Supporting Pages'),
    ]
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='link_issues')
    issue_type = models.CharField(max_length=50, choices=ISSUE_TYPES)
    severity = models.CharField(max_length=20, choices=[
        ('high', 'High'), ('medium', 'Medium'), ('low', 'Low'),
    ], default='medium')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='link_issues', null=True, blank=True)
    related_pages = models.ManyToManyField(Page, related_name='related_link_issues', blank=True)
    description = models.TextField()
    recommendation = models.TextField(blank=True)
    anchor_text = models.CharField(max_length=500, blank=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'link_issues'
        ordering = ['-severity', '-created_at']

    def __str__(self):
        return f"{self.get_issue_type_display()}: {self.description[:50]}"


class SEOData(models.Model):
    page = models.OneToOneField(Page, on_delete=models.CASCADE, related_name='seo_data')
    meta_title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    meta_keywords = models.CharField(max_length=500, blank=True)
    h1_count = models.IntegerField(default=0)
    h1_text = models.CharField(max_length=500, blank=True)
    h2_count = models.IntegerField(default=0)
    h2_texts = models.JSONField(default=list)
    h3_count = models.IntegerField(default=0)
    h3_texts = models.JSONField(default=list)
    internal_links_count = models.IntegerField(default=0)
    external_links_count = models.IntegerField(default=0)
    internal_links = models.JSONField(default=list)
    external_links = models.JSONField(default=list)
    images_count = models.IntegerField(default=0)
    images_without_alt = models.IntegerField(default=0)
    images = models.JSONField(default=list)
    word_count = models.IntegerField(default=0)
    reading_time_minutes = models.FloatField(default=0)
    seo_score = models.IntegerField(default=0)
    issues = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    has_canonical = models.BooleanField(default=False)
    canonical_url = models.URLField(blank=True)
    has_schema = models.BooleanField(default=False)
    schema_type = models.CharField(max_length=100, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)
    scan_version = models.CharField(max_length=50, default='1.0')

    class Meta:
        db_table = 'seo_data'
        ordering = ['-scanned_at']

    def __str__(self):
        return f"SEO Data for {self.page.title}"


class ContentJob(models.Model):
    """
    Persistent content generation job — replaces the in-memory _jobs dict.
    Survives server restarts and supports async processing.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    job_id = models.CharField(max_length=36, unique=True, db_index=True)
    site = models.ForeignKey(
        'sites.Site', on_delete=models.CASCADE, related_name='content_jobs'
    )
    page_id = models.CharField(max_length=255, blank=True, null=True)
    wp_post_id = models.IntegerField(blank=True, null=True)
    job_type = models.CharField(max_length=50, default='content_generation')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    result = models.JSONField(blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'content_jobs'
        ordering = ['-created_at']

    def __str__(self):
        return f"ContentJob {self.job_id} [{self.status}]"




# ---------------------------------------------------------------------------
# V2 / V2.2 Models — class stubs matching existing migrations
# Tables were created by migrations 0006, 0007, 0013, 0014, 0015, 0018.
# managed=False prevents makemigrations from generating conflicting diffs.
# ---------------------------------------------------------------------------

class SiloDefinition(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True)
    hub_page_url = models.URLField(max_length=2048, blank=True)
    hub_page_id = models.IntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=50, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'silo_definitions'

    def __str__(self):
        return self.name


class SiloKeyword(models.Model):
    silo = models.ForeignKey(SiloDefinition, on_delete=models.CASCADE, related_name='keywords', null=True, blank=True)
    keyword = models.CharField(max_length=500)
    keyword_type = models.CharField(max_length=50, default='supporting')
    search_volume = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'silo_keywords'

    def __str__(self):
        return self.keyword


class KeywordAssignment(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True)
    silo = models.ForeignKey(SiloDefinition, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments')
    keyword = models.CharField(max_length=255, db_index=True)
    page_url = models.URLField(max_length=2048, blank=True)
    page_id = models.IntegerField(null=True, blank=True)
    page_title = models.CharField(max_length=1024, blank=True)
    page_type = models.CharField(max_length=50, default='general')
    assignment_source = models.CharField(max_length=50, default='manual')
    status = models.CharField(max_length=20, default='active')
    gsc_impressions = models.IntegerField(default=0)
    gsc_clicks = models.IntegerField(default=0)
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'keyword_assignments'

    def __str__(self):
        return f"{self.keyword} → {self.page_url}"


class KeywordAssignmentHistory(models.Model):
    assignment = models.ForeignKey(KeywordAssignment, on_delete=models.CASCADE, related_name='history', null=True, blank=True)
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True)
    keyword = models.CharField(max_length=500)
    previous_url = models.URLField(max_length=2048, blank=True)
    new_url = models.URLField(max_length=2048, blank=True)
    previous_page_type = models.CharField(max_length=100, blank=True)
    new_page_type = models.CharField(max_length=100, blank=True)
    action = models.CharField(max_length=50, default='assign')
    reason = models.TextField(blank=True)
    performed_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'keyword_assignment_history'

    def __str__(self):
        return f"{self.action}: {self.keyword}"


class PageMetadata(models.Model):
    page = models.OneToOneField(Page, on_delete=models.CASCADE, related_name='metadata', null=True, blank=True)
    page_url = models.URLField(max_length=2048, blank=True)
    title_tag = models.CharField(max_length=1024, blank=True)
    h1_tag = models.CharField(max_length=1024, blank=True)
    meta_description = models.TextField(blank=True)
    is_indexable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'page_metadata'

    def __str__(self):
        return f"Metadata: {self.page_url}"


class CannibalizationConflict(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='cannibalization_conflicts')
    keyword = models.CharField(max_length=500)
    conflict_type = models.CharField(max_length=100, blank=True)
    severity = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=50, default='open')
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'cannibalization_conflicts'

    def __str__(self):
        return f"Conflict: {self.keyword}"


class ConflictPage(models.Model):
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.CASCADE, related_name='pages', null=True, blank=True)
    page_url = models.URLField(max_length=2048, blank=True)
    page_id = models.IntegerField(null=True, blank=True)
    page_type = models.CharField(max_length=100, blank=True)
    is_recommended_winner = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'conflict_pages'

    def __str__(self):
        return self.page_url


class ConflictResolution(models.Model):
    # UUIDField primary key — matches migration 0007
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.CASCADE, related_name='resolutions', null=True, blank=True)
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='conflict_resolutions', null=True, blank=True)
    redirect = models.ForeignKey('RedirectRegistry', on_delete=models.SET_NULL, null=True, blank=True, related_name='conflict_resolutions')
    action_type = models.CharField(max_length=30)
    winner_url = models.CharField(max_length=2048, blank=True, null=True)
    loser_url = models.CharField(max_length=2048, blank=True, null=True)
    redirect_type = models.IntegerField(blank=True, null=True)
    merge_brief = models.TextField(blank=True, null=True)
    content_merged = models.BooleanField(default=False)
    internal_links_updated = models.IntegerField(default=0)
    keyword_reassigned = models.BooleanField(default=False)
    previous_keyword_owner = models.CharField(max_length=2048, blank=True, null=True)
    new_keyword_owner = models.CharField(max_length=2048, blank=True, null=True)
    recommended_by = models.CharField(max_length=30, default='siloq')
    approved_by = models.CharField(max_length=255, blank=True, null=True)
    approval_rating = models.CharField(max_length=10, blank=True, null=True)
    verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)
    verification_status = models.CharField(max_length=30, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'conflict_resolutions'

    def __str__(self):
        return f"{self.action_type} resolution"


class RedirectRegistry(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='redirects')
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.SET_NULL, null=True, blank=True)
    source_url = models.URLField(max_length=2048)
    target_url = models.URLField(max_length=2048)
    redirect_type = models.IntegerField(default=301)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=50, default='active')
    is_verified = models.BooleanField(default=False)
    chain_depth = models.IntegerField(default=0)
    final_destination = models.URLField(max_length=2048, blank=True)
    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'redirect_registry'

    def __str__(self):
        return f"{self.source_url} → {self.target_url}"


class ContentHealthScore(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='content_health_scores')
    page_url = models.URLField(max_length=2048, blank=True)
    page_id = models.IntegerField(null=True, blank=True)
    health_score = models.FloatField(default=0.0)
    health_status = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'content_health_scores'

    def __str__(self):
        return f"ContentHealth {self.page_url}"


class FreshnessAlert(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='freshness_alerts')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, null=True, blank=True)
    page_url = models.URLField(max_length=2048, blank=True)
    alert_level = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=50, default='active')
    snoozed_until = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'freshness_alerts'

    def __str__(self):
        return f"FreshnessAlert {self.page_url}"


class ContentAuditLog(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='content_audits')
    audit_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=50, default='pending')
    total_pages_audited = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'content_audit_log'

    def __str__(self):
        return f"ContentAudit [{self.status}]"


class ValidationLog(models.Model):
    # UUIDField primary key — matches migration 0007
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True)
    proposed_title = models.CharField(max_length=500, blank=True, null=True)
    proposed_slug = models.CharField(max_length=500, blank=True, null=True)
    proposed_h1 = models.CharField(max_length=500, blank=True, null=True)
    proposed_keyword = models.CharField(max_length=500, blank=True, null=True)
    proposed_page_type = models.CharField(max_length=30, blank=True, null=True)
    overall_status = models.CharField(max_length=10)
    blocking_check = models.CharField(max_length=50, blank=True, null=True)
    check_results = models.JSONField(default=dict)
    user_action = models.CharField(max_length=30, blank=True, null=True)
    user_acknowledged_warnings = models.BooleanField(default=False)
    validation_source = models.CharField(max_length=30, default='generation')
    triggered_by = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'validation_log'

    def __str__(self):
        return f"ValidationLog {self.overall_status}"


class SiloHealthScore(models.Model):
    silo = models.ForeignKey(SiloDefinition, on_delete=models.CASCADE, related_name='health_scores', null=True, blank=True)
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True)
    score = models.FloatField(default=0.0)
    component_scores = models.JSONField(default=dict)
    page_count = models.IntegerField(default=0)
    details = models.JSONField(default=dict)
    trigger = models.CharField(max_length=100, blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'silo_health_scores'

    def __str__(self):
        return f"SiloHealth silo={self.silo_id} score={self.score}"


class SiteEntityProfile(models.Model):
    site = models.OneToOneField('sites.Site', on_delete=models.CASCADE, related_name='entity_profile', null=True, blank=True)
    business_name = models.CharField(max_length=255, blank=True)
    founder_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    founding_year = models.IntegerField(null=True, blank=True)
    num_employees = models.CharField(max_length=50, blank=True)
    price_range = models.CharField(max_length=20, blank=True)
    languages = models.JSONField(default=list)
    payment_methods = models.JSONField(default=list)
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default='US')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    service_cities = models.JSONField(default=list)
    service_zips = models.JSONField(default=list)
    service_radius_miles = models.IntegerField(null=True, blank=True)
    hours = models.JSONField(default=dict)
    categories = models.JSONField(default=list)
    certifications = models.JSONField(default=list)
    license_numbers = models.JSONField(default=list)
    url_facebook = models.URLField(blank=True, max_length=2048)
    url_instagram = models.URLField(blank=True, max_length=2048)
    url_linkedin = models.URLField(blank=True, max_length=2048)
    url_twitter = models.URLField(blank=True, max_length=2048)
    url_youtube = models.URLField(blank=True, max_length=2048)
    url_tiktok = models.URLField(blank=True, max_length=2048)
    gbp_url = models.URLField(blank=True, max_length=2048)
    google_place_id = models.CharField(max_length=255, blank=True)
    gbp_star_rating = models.FloatField(null=True, blank=True)
    gbp_review_count = models.IntegerField(null=True, blank=True)
    gbp_reviews = models.JSONField(default=list)
    gbp_last_synced = models.DateTimeField(null=True, blank=True)

    # V1 additions — brands, logo, Yelp, team, SAB flag
    logo_url = models.URLField(blank=True, max_length=500,
        help_text="Publicly accessible URL for the business logo (required for schema)")
    brands_used = SafeJSONField(default=list, blank=True,
        help_text="Brands/products the business installs, sells, or uses (e.g. Generac, Trane)")
    url_yelp = models.URLField(blank=True, max_length=500,
        help_text="Yelp business profile URL (high-authority sameAs entity signal)")
    team_members = SafeJSONField(default=list, blank=True,
        help_text="List of {name, title, linkedin_url, bio} — used for E-E-A-T and About Us analysis")
    is_service_area_business = models.BooleanField(default=False,
        help_text="True if business hides physical address and serves a geographic area (SAB)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'seo_siteentityprofile'

    def __str__(self):
        return f"EntityProfile: {self.business_name or self.site_id}"


class PageAnalysis(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='page_analyses')
    page_url = models.URLField(max_length=2048)
    page_title = models.CharField(max_length=500, blank=True)
    # gsc_data and wp_meta are NOT NULL in DB (created with default=dict in migration 0014)
    # generated_schema is NOT NULL in DB (added with default=dict in migration 0017)
    # Use default=dict so Django inserts {} instead of NULL when not provided
    gsc_data = models.JSONField(default=dict)
    wp_meta = models.JSONField(default=dict)
    geo_recommendations = models.JSONField(default=list)
    seo_recommendations = models.JSONField(default=list)
    cro_recommendations = models.JSONField(default=list)
    geo_score = models.IntegerField(null=True, blank=True)
    seo_score = models.IntegerField(null=True, blank=True)
    cro_score = models.IntegerField(null=True, blank=True)
    overall_score = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, default='pending')
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    generated_schema = models.JSONField(default=dict)

    class Meta:
        managed = False
        db_table = 'page_analyses'

    def __str__(self):
        return f"Analysis {self.id} — {self.page_url} [{self.status}]"


class SlugChangeLog(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, null=True, blank=True, related_name='slug_changes')
    page_id = models.IntegerField(null=True, blank=True)
    old_url = models.CharField(max_length=2048)
    old_slug = models.CharField(max_length=500, blank=True)
    new_url = models.CharField(max_length=2048)
    new_slug = models.CharField(max_length=500, blank=True)
    redirect = models.ForeignKey(RedirectRegistry, on_delete=models.SET_NULL, null=True, blank=True)
    redirect_status = models.CharField(max_length=50, blank=True)
    slug_change_status = models.CharField(max_length=50, default='pending')
    reason = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True, null=True)
    changed_by = models.CharField(max_length=255, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'slug_change_log'

    def __str__(self):
        return f"{self.old_url} → {self.new_url} [{self.slug_change_status}]"
