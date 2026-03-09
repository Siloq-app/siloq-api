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
from django.contrib.auth import get_user_model
from sites.models import Site

User = get_user_model()


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
    
    # Related pages for supporting content calculation
    related_pages = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=False,
        related_name='related_to_pages',
        help_text="Pages that support or are supported by this page"
    )
    
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


class GSCData(models.Model):
    """
    Google Search Console performance data for pages.
    Stores impressions, clicks, position, and CTR for specific queries.
    """
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='gsc_data'
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='gsc_data'
    )
    
    # Query and metrics
    query = models.CharField(
        max_length=500,
        help_text="The search query"
    )
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    position = models.FloatField(default=0)
    ctr = models.FloatField(default=0)
    
    # Date range
    date_start = models.DateField()
    date_end = models.DateField()
    
    # Device and location breakdowns (optional)
    device = models.CharField(
        max_length=20,
        blank=True,
        help_text="Device type: desktop, mobile, tablet"
    )
    country = models.CharField(
        max_length=2,
        blank=True,
        help_text="Country code"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gsc_data'
        ordering = ['-impressions', '-clicks']
        unique_together = [
            ['page', 'site', 'query', 'date_start', 'date_end', 'device', 'country']
        ]
        indexes = [
            models.Index(fields=['page', 'query']),
            models.Index(fields=['site', 'query']),
            models.Index(fields=['impressions']),
            models.Index(fields=['position']),
        ]

    def __str__(self):
        return f"GSC: {self.query} → {self.page.title} ({self.impressions} impressions)"


class Conflict(models.Model):
    """
    Keyword cannibalization conflicts between pages.
    Tracks when multiple pages compete for the same search query.
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='conflicts'
    )
    
    # The conflicting pages
    page1 = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='conflicts_as_page1'
    )
    page2 = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='conflicts_as_page2'
    )
    
    # The query string they're competing for
    query_string = models.CharField(
        max_length=500,
        help_text="The GSC query string these pages compete for"
    )
    
    # Winner determination
    winner_page = models.ForeignKey(
        Page,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_conflicts',
        help_text="The page that should rank for this query"
    )
    
    # Location differentiation
    location_differentiation = models.JSONField(
        default=list,
        help_text="Location-based differentiation data"
    )
    
    # Recommendation
    recommendation = models.TextField(
        blank=True,
        help_text="AI-generated recommendation for resolving this conflict"
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('in_approval_queue', 'In Approval Queue'),
            ('resolved', 'Resolved'),
        ],
        default='active'
    )
    
    is_dismissed = models.BooleanField(default=False)
    severity_score = models.IntegerField(
        default=50,
        help_text="Severity score (0-100)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'conflicts'
        ordering = ['-severity_score', '-created_at']
        unique_together = [['site', 'page1', 'page2', 'query_string']]
        indexes = [
            models.Index(fields=['site', 'status']),
            models.Index(fields=['query_string']),
            models.Index(fields=['severity_score']),
        ]

    def __str__(self):
        return f"Conflict: {self.query_string} between {self.page1.title} and {self.page2.title}"


class ContentJob(models.Model):
    """
    Content generation and management jobs.
    Tracks content creation from suggestion to completion.
    """
    JOB_TYPES = [
        ('conflict_resolution', 'Conflict Resolution'),
        ('supporting_content', 'Supporting Content'),
        ('money_page_optimization', 'Money Page Optimization'),
        ('homepage_optimization', 'Homepage Optimization'),
    ]
    
    STATUSES = [
        ('pending', 'Pending'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='content_jobs'
    )
    
    # Job details
    job_type = models.CharField(max_length=50, choices=JOB_TYPES)
    topic = models.CharField(max_length=500, blank=True)
    recommendation = models.TextField(blank=True)
    
    # Associated objects
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='content_jobs',
        null=True,
        blank=True
    )
    conflict = models.ForeignKey(
        Conflict,
        on_delete=models.CASCADE,
        related_name='content_jobs',
        null=True,
        blank=True
    )
    target_page = models.ForeignKey(
        Page,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='targeted_content_jobs'
    )
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUSES, default='pending')
    priority = models.CharField(
        max_length=10,
        choices=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
        ],
        default='medium'
    )
    
    # Content details
    estimated_word_count = models.IntegerField(null=True, blank=True)
    actual_word_count = models.IntegerField(null=True, blank=True)
    generated_content = models.TextField(blank=True)
    
    # WordPress integration
    wp_post_id = models.IntegerField(null=True, blank=True)
    wp_status = models.CharField(max_length=20, blank=True)
    
    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_content_jobs'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'content_jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['site', 'status']),
            models.Index(fields=['job_type']),
            models.Index(fields=['priority']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.get_job_type_display()}: {self.topic or self.recommendation[:50]}"


# ── Model stubs for imports that reference planned models ──────────────────────
# These are managed=False so Django won't try to create/migrate tables.
# They exist solely to prevent ImportError in views that reference them.
# Replace with real models when building the corresponding features.

class SiloDefinition(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='silo_definitions')
    name = models.CharField(max_length=255)
    target_page = models.ForeignKey(Page, on_delete=models.SET_NULL, null=True, blank=True, related_name='silo_target')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'silo_definitions'

    def __str__(self):
        return self.name


class SiloKeyword(models.Model):
    silo = models.ForeignKey(SiloDefinition, on_delete=models.CASCADE, related_name='keywords')
    keyword = models.CharField(max_length=500)
    search_volume = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'silo_keywords'


class KeywordAssignment(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='keyword_assignments')
    keyword = models.CharField(max_length=500)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, null=True, blank=True, related_name='keyword_assignments')
    silo = models.ForeignKey(SiloDefinition, on_delete=models.SET_NULL, null=True, blank=True, related_name='assignments')
    status = models.CharField(max_length=20, default='active')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'keyword_assignments'


class KeywordAssignmentHistory(models.Model):
    assignment = models.ForeignKey(KeywordAssignment, on_delete=models.CASCADE, null=True, blank=True, related_name='history')
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='keyword_history')
    keyword = models.CharField(max_length=500)
    action = models.CharField(max_length=50)
    old_page = models.ForeignKey(Page, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    new_page = models.ForeignKey(Page, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'keyword_assignment_history'


class PageMetadata(models.Model):
    page = models.OneToOneField(Page, on_delete=models.CASCADE, related_name='metadata')
    word_count = models.IntegerField(default=0)
    readability_score = models.FloatField(default=0)
    last_crawled = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'page_metadata'


class CannibalizationConflict(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='cannibalization_conflicts')
    keyword = models.CharField(max_length=500)
    severity = models.CharField(max_length=20, default='medium')
    status = models.CharField(max_length=20, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'cannibalization_conflicts'


class ConflictPage(models.Model):
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.CASCADE, related_name='conflict_pages')
    page = models.ForeignKey(Page, on_delete=models.CASCADE)
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    position = models.FloatField(default=0)

    class Meta:
        managed = False
        db_table = 'conflict_pages'


class ConflictResolution(models.Model):
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.CASCADE, related_name='resolutions')
    resolution_type = models.CharField(max_length=50)
    notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'conflict_resolutions'


class RedirectRegistry(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='redirects')
    source_url = models.URLField()
    target_url = models.URLField()
    redirect_type = models.CharField(max_length=10, default='301')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'redirect_registry'


class PageAnalysis(models.Model):
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='analyses')
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='page_analyses', null=True)
    analysis_data = models.JSONField(default=dict)
    score = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'page_analyses'


class SiteEntityProfile(models.Model):
    site = models.OneToOneField('sites.Site', on_delete=models.CASCADE, related_name='entity_profile')
    business_name = models.CharField(max_length=255, blank=True)
    business_type = models.CharField(max_length=50, blank=True)
    main_services = models.JSONField(default=list)
    service_areas = models.JSONField(default=list)
    logo_url = models.URLField(blank=True)
    brands_used = models.JSONField(default=list)
    url_yelp = models.URLField(blank=True)
    team_members = models.JSONField(default=list)
    is_service_area_business = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'site_entity_profiles'


class SlugChangeLog(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='slug_changes')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='slug_changes')
    old_slug = models.CharField(max_length=500)
    new_slug = models.CharField(max_length=500)
    redirect_created = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'slug_change_log'


class SiloHealthScore(models.Model):
    silo = models.ForeignKey(SiloDefinition, on_delete=models.CASCADE, related_name='health_scores')
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='silo_health_scores')
    score = models.FloatField(default=0)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'silo_health_scores'


class FreshnessAlert(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='freshness_alerts')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='freshness_alerts')
    alert_type = models.CharField(max_length=50)
    message = models.TextField(blank=True)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'freshness_alerts'


class ContentHealthScore(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='content_health_scores')
    score = models.FloatField(default=0)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'content_health_scores'


class ContentAuditLog(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='content_audit_logs')
    action = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'content_audit_logs'


class LifecycleQueue(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='lifecycle_queue')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='lifecycle_entries')
    action = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default='pending')
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'lifecycle_queue'


class SiteGSCPageData(models.Model):
    """Per-page GSC performance data, synced from Google Search Console."""
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='gsc_pages')
    page = models.ForeignKey('seo.Page', on_delete=models.CASCADE, null=True, blank=True, related_name='gsc_page_data')
    url = models.URLField(max_length=2048)
    impressions_28d = models.IntegerField(default=0)
    clicks_28d = models.IntegerField(default=0)
    avg_position = models.FloatField(null=True, blank=True)
    top_queries = models.JSONField(default=list)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'seo_gsc_page_data'
        unique_together = [('site', 'url')]

    def __str__(self):
        return f"GSC {self.url} ({self.clicks_28d}c / {self.impressions_28d}i)"


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
class ValidationLog(models.Model):
    site = models.ForeignKey('sites.Site', on_delete=models.CASCADE, related_name='validation_logs')
    page = models.ForeignKey(Page, on_delete=models.CASCADE, null=True, blank=True, related_name='validation_logs')
    validation_type = models.CharField(max_length=50)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'validation_logs'


class SiteIntelligence(models.Model):
    site = models.OneToOneField('sites.Site', on_delete=models.CASCADE, related_name='intelligence')
    business_type = models.CharField(max_length=50, default='general')
    primary_goal = models.TextField(blank=True)
    raw_analysis = models.JSONField(default=dict)
    hub_pages = models.JSONField(default=list)
    spoke_pages = models.JSONField(default=list)
    orphan_pages = models.JSONField(default=list)
    architecture_problems = models.JSONField(default=list)
    content_gaps = models.JSONField(default=list)
    cannibalization_risks = models.JSONField(default=list)
    generated_at = models.DateTimeField(auto_now=True)
    generation_error = models.TextField(blank=True)

    class Meta:
        app_label = 'seo'
