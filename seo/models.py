"""
SEO models — Page/Link analysis (v1) + Anti-Cannibalization Engine (v2).

v2 tables are organised into five domains:
  1. Core Registry        — SiloDefinition, SiloKeyword, KeywordAssignment, KeywordAssignmentHistory, PageMetadata
  2. Detection & Conflicts — CannibalizationConflict, ConflictPage, ConflictResolution
  3. Content Lifecycle     — ContentHealthScore, FreshnessAlert, LifecycleQueue, ContentAuditLog
  4. Redirect Management   — RedirectRegistry
  5. Validation & Preflight — ValidationLog
"""

import uuid
from django.db import models
from sites.models import Site


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

    parent_silo = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supporting_pages')
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


# ═════════════════════════════════════════════════════════════
# V2 — ANTI-CANNIBALIZATION ENGINE
# ═════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────
# DOMAIN 1: CORE REGISTRY
# ─────────────────────────────────────────────────────────────

class SiloDefinition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='silo_definitions')
    name = models.CharField(max_length=255)
    slug = models.CharField(max_length=255)
    hub_page_url = models.CharField(max_length=2048, blank=True, null=True)
    hub_page_id = models.IntegerField(null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'silo_definitions'
        unique_together = [('site', 'slug')]
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['site', 'status']),
        ]

    def __str__(self):
        return f"{self.name} ({self.site.name})"


class SiloKeyword(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    silo = models.ForeignKey(SiloDefinition, on_delete=models.CASCADE, related_name='keywords')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='silo_keywords')
    keyword = models.CharField(max_length=500)
    keyword_type = models.CharField(max_length=20, default='supporting')
    search_volume = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'silo_keywords'
        unique_together = [('silo', 'keyword')]
        indexes = [
            models.Index(fields=['silo']),
            models.Index(fields=['site']),
            models.Index(fields=['keyword']),
        ]

    def __str__(self):
        return f"{self.keyword} → {self.silo.name}"


class KeywordAssignment(models.Model):
    """
    v2 keyword assignment — one keyword per site, database-enforced.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='keyword_assignments')
    silo = models.ForeignKey(SiloDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='keyword_assignments')
    keyword = models.CharField(max_length=500)
    page_url = models.CharField(max_length=2048)
    page_id = models.IntegerField(null=True, blank=True)
    page_title = models.CharField(max_length=500, blank=True, null=True)
    page_type = models.CharField(max_length=30, default='spoke')
    keyword_type = models.CharField(max_length=20, default='primary')
    assignment_source = models.CharField(max_length=30, default='auto')
    status = models.CharField(max_length=20, default='active')
    gsc_impressions = models.IntegerField(default=0)
    gsc_clicks = models.IntegerField(default=0)
    gsc_avg_position = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    gsc_last_synced = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deprecated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'keyword_assignments'
        unique_together = [('keyword', 'site')]
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['silo']),
            models.Index(fields=['site', 'page_url']),
            models.Index(fields=['site', 'status']),
            models.Index(fields=['site', 'page_type']),
        ]

    def __str__(self):
        return f"{self.keyword} → {self.page_url}"


class KeywordAssignmentHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(KeywordAssignment, on_delete=models.CASCADE,
        related_name='history')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='keyword_assignment_history')
    keyword = models.CharField(max_length=500)
    previous_url = models.CharField(max_length=2048, blank=True, null=True)
    new_url = models.CharField(max_length=2048, blank=True, null=True)
    previous_page_type = models.CharField(max_length=30, blank=True, null=True)
    new_page_type = models.CharField(max_length=30, blank=True, null=True)
    action = models.CharField(max_length=30)
    reason = models.TextField(blank=True, null=True)
    performed_by = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'keyword_assignment_history'
        indexes = [
            models.Index(fields=['assignment']),
            models.Index(fields=['site']),
            models.Index(fields=['keyword']),
        ]

    def __str__(self):
        return f"{self.action}: {self.keyword}"


class PageMetadata(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='page_metadata')
    page_url = models.CharField(max_length=2048)
    page_id = models.IntegerField(null=True, blank=True)
    post_type = models.CharField(max_length=50, blank=True, null=True)
    taxonomy = models.CharField(max_length=100, blank=True, null=True)
    term_id = models.IntegerField(null=True, blank=True)
    parent_id = models.IntegerField(null=True, blank=True)
    title_tag = models.CharField(max_length=500, blank=True, null=True)
    h1_tag = models.CharField(max_length=500, blank=True, null=True)
    meta_description = models.CharField(max_length=500, blank=True, null=True)
    canonical_url = models.CharField(max_length=2048, blank=True, null=True)
    http_status = models.IntegerField(null=True, blank=True)
    redirect_target = models.CharField(max_length=2048, blank=True, null=True)
    is_indexable = models.BooleanField(default=True)
    noindex_source = models.CharField(max_length=50, blank=True, null=True)
    has_canonical_self = models.BooleanField(default=True)
    canonical_points_to = models.CharField(max_length=2048, blank=True, null=True)
    silo = models.ForeignKey(SiloDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='page_metadata')
    url_depth = models.IntegerField(null=True, blank=True)
    word_count = models.IntegerField(default=0)
    has_schema_markup = models.BooleanField(default=False)
    internal_links_in = models.IntegerField(default=0)
    internal_links_out = models.IntegerField(default=0)
    backlink_count = models.IntegerField(default=0)
    last_crawled = models.DateTimeField(null=True, blank=True)
    last_modified = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'page_metadata'
        unique_together = [('site', 'page_url')]
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['page_url']),
            models.Index(fields=['site', 'is_indexable']),
            models.Index(fields=['site', 'http_status']),
            models.Index(fields=['silo']),
            models.Index(fields=['site', 'post_type']),
            models.Index(fields=['site', 'taxonomy']),
        ]

    def __str__(self):
        return f"{self.page_url}"


# ─────────────────────────────────────────────────────────────
# DOMAIN 2: DETECTION & CONFLICTS
# ─────────────────────────────────────────────────────────────

class CannibalizationConflict(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='cannibalization_conflicts')
    keyword = models.CharField(max_length=500)
    conflict_type = models.CharField(max_length=50)
    severity = models.CharField(max_length=20)
    raw_score = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    adjusted_score = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    keyword_score = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    semantic_score = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    gsc_query_overlap_score = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    intent_score = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    impression_multiplier = models.DecimalField(max_digits=3, decimal_places=2, default=1.0)
    status = models.CharField(max_length=30, default='open')
    resolution_type = models.CharField(max_length=30, blank=True, null=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    detection_source = models.CharField(max_length=30, default='pipeline')
    last_checked = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=255, blank=True, null=True)
    max_impressions = models.IntegerField(default=0)
    shared_gsc_queries = models.JSONField(default=list)
    # NEW: Flip-flop detection metadata
    flip_flop_detected = models.BooleanField(default=False)
    flip_flop_correlation = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    position_volatility = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)  # For flip-flop daily_positions and other future metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cannibalization_conflicts'
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['site', 'status']),
            models.Index(fields=['site', 'severity']),
            models.Index(fields=['keyword']),
            models.Index(fields=['detected_at']),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.keyword} ({self.status})"


class ConflictPage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.CASCADE,
        related_name='pages')
    page_url = models.CharField(max_length=2048)
    page_id = models.IntegerField(null=True, blank=True)
    page_type = models.CharField(max_length=30, blank=True, null=True)
    gsc_impressions = models.IntegerField(default=0)
    gsc_clicks = models.IntegerField(default=0)
    gsc_avg_position = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    backlink_count = models.IntegerField(default=0)
    is_recommended_winner = models.BooleanField(default=False)
    winner_score = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    is_indexable = models.BooleanField(default=True)
    http_status = models.IntegerField(default=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'conflict_pages'
        indexes = [
            models.Index(fields=['conflict']),
            models.Index(fields=['page_url']),
        ]

    def __str__(self):
        return f"{self.page_url} (conflict {self.conflict_id})"


# ─────────────────────────────────────────────────────────────
# DOMAIN 4: REDIRECT MANAGEMENT (before ConflictResolution for FK)
# ─────────────────────────────────────────────────────────────

class RedirectRegistry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='redirects')
    source_url = models.CharField(max_length=2048)
    target_url = models.CharField(max_length=2048)
    redirect_type = models.IntegerField(default=301)
    reason = models.CharField(max_length=50)
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='redirects')
    status = models.CharField(max_length=20, default='active')
    is_verified = models.BooleanField(default=False)
    last_verified = models.DateTimeField(null=True, blank=True)
    verification_status = models.CharField(max_length=30, blank=True, null=True)
    chain_depth = models.IntegerField(default=0)
    final_destination = models.CharField(max_length=2048, blank=True, null=True)
    last_hit = models.DateTimeField(null=True, blank=True)
    total_hits = models.IntegerField(default=0)
    created_by = models.CharField(max_length=255, default='siloq_system')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'redirect_registry'
        unique_together = [('site', 'source_url')]
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['source_url']),
            models.Index(fields=['target_url']),
            models.Index(fields=['site', 'status']),
            models.Index(fields=['site', 'reason']),
        ]

    def __str__(self):
        return f"{self.source_url} → {self.target_url} ({self.redirect_type})"


# ─────────────────────────────────────────────────────────────
# DOMAIN 2 (cont.): CONFLICT RESOLUTIONS
# ─────────────────────────────────────────────────────────────

class ConflictResolution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conflict = models.ForeignKey(CannibalizationConflict, on_delete=models.CASCADE,
        related_name='resolutions')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='conflict_resolutions')
    action_type = models.CharField(max_length=30)
    winner_url = models.CharField(max_length=2048, blank=True, null=True)
    loser_url = models.CharField(max_length=2048, blank=True, null=True)
    redirect = models.ForeignKey(RedirectRegistry, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conflict_resolutions')
    redirect_type = models.IntegerField(null=True, blank=True)
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
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_status = models.CharField(max_length=30, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'conflict_resolutions'
        indexes = [
            models.Index(fields=['conflict']),
            models.Index(fields=['site']),
            models.Index(fields=['action_type']),
        ]

    def __str__(self):
        return f"{self.action_type}: {self.conflict_id}"


# ─────────────────────────────────────────────────────────────
# DOMAIN 3: CONTENT LIFECYCLE
# ─────────────────────────────────────────────────────────────

class ContentHealthScore(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='content_health_scores')
    page_url = models.CharField(max_length=2048)
    page_id = models.IntegerField(null=True, blank=True)
    health_score = models.IntegerField()
    health_status = models.CharField(max_length=20)
    impressions_score = models.IntegerField(default=0)
    clicks_score = models.IntegerField(default=0)
    position_score = models.IntegerField(default=0)
    freshness_score = models.IntegerField(default=0)
    backlink_score = models.IntegerField(default=0)
    internal_link_score = models.IntegerField(default=0)
    gsc_impressions = models.IntegerField(default=0)
    gsc_clicks = models.IntegerField(default=0)
    gsc_avg_position = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    days_since_modified = models.IntegerField(default=0)
    backlink_count = models.IntegerField(default=0)
    internal_links_in = models.IntegerField(default=0)
    recommended_action = models.CharField(max_length=30, blank=True, null=True)
    recommended_action_reason = models.TextField(blank=True, null=True)
    redirect_target_url = models.CharField(max_length=2048, blank=True, null=True)
    scored_at = models.DateTimeField(auto_now_add=True)
    scoring_period_start = models.DateField(null=True, blank=True)
    scoring_period_end = models.DateField(null=True, blank=True)
    previous_score = models.IntegerField(null=True, blank=True)
    score_change = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'content_health_scores'
        unique_together = [('site', 'page_url', 'scored_at')]
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['page_url']),
            models.Index(fields=['site', 'health_status']),
            models.Index(fields=['scored_at']),
            models.Index(fields=['site', 'recommended_action']),
        ]

    def __str__(self):
        return f"{self.page_url}: {self.health_score} ({self.health_status})"


class FreshnessAlert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='freshness_alerts')
    page_url = models.CharField(max_length=2048)
    page_id = models.IntegerField(null=True, blank=True)
    page_type = models.CharField(max_length=30, blank=True, null=True)
    alert_level = models.CharField(max_length=20)
    days_since_modified = models.IntegerField()
    staleness_threshold = models.IntegerField()
    alert_message = models.TextField()
    status = models.CharField(max_length=20, default='active')
    snoozed_until = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=255, blank=True, null=True)
    has_traffic = models.BooleanField(default=False)
    gsc_clicks_28d = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'freshness_alerts'
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['site', 'status']),
            models.Index(fields=['site', 'alert_level']),
        ]

    def __str__(self):
        return f"[{self.alert_level}] {self.page_url}"


class LifecycleQueue(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='lifecycle_queue')
    action_type = models.CharField(max_length=30)
    priority = models.CharField(max_length=5)
    source_type = models.CharField(max_length=30)
    source_id = models.UUIDField(null=True, blank=True)
    primary_page_url = models.CharField(max_length=2048)
    secondary_page_url = models.CharField(max_length=2048, blank=True, null=True)
    recommendation_summary = models.TextField()
    recommendation_detail = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, default='pending')
    approved_by = models.CharField(max_length=255, blank=True, null=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    execution_steps = models.JSONField(null=True, blank=True)
    execution_errors = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'lifecycle_queue'
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['site', 'status']),
            models.Index(fields=['site', 'priority']),
            models.Index(fields=['site', 'action_type']),
        ]

    def __str__(self):
        return f"[{self.priority}] {self.action_type}: {self.primary_page_url}"


class ContentAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='content_audit_logs')
    audit_type = models.CharField(max_length=30)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    total_pages_audited = models.IntegerField(default=0)
    pages_healthy = models.IntegerField(default=0)
    pages_refresh = models.IntegerField(default=0)
    pages_monitor = models.IntegerField(default=0)
    pages_kill = models.IntegerField(default=0)
    new_conflicts_found = models.IntegerField(default=0)
    conflicts_resolved_since_last = models.IntegerField(default=0)
    queue_items_created = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default='running')
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'content_audit_log'
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['audit_type']),
        ]

    def __str__(self):
        return f"{self.audit_type} @ {self.started_at} ({self.status})"


# ─────────────────────────────────────────────────────────────
# DOMAIN 5: VALIDATION & PREFLIGHT
# ─────────────────────────────────────────────────────────────

class ValidationLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='validation_logs')
    proposed_title = models.CharField(max_length=500, blank=True, null=True)
    proposed_slug = models.CharField(max_length=500, blank=True, null=True)
    proposed_h1 = models.CharField(max_length=500, blank=True, null=True)
    proposed_keyword = models.CharField(max_length=500, blank=True, null=True)
    proposed_silo = models.ForeignKey(SiloDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validation_logs')
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
        db_table = 'validation_log'
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['overall_status']),
            models.Index(fields=['proposed_keyword']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"[{self.overall_status}] {self.proposed_keyword or self.proposed_title}"


# ─────────────────────────────────────────────────────────────
# DOMAIN 6: PAGE CONTENT OPTIMIZATION (Three-Layer Model)
# ─────────────────────────────────────────────────────────────

class PageAnalysis(models.Model):
    """
    AI-driven analysis of a single page against the Three-Layer Content Model
    (GEO → SEO → CRO). Each analysis captures input data snapshots (GSC +
    WordPress meta) and the AI-generated recommendations for all three layers.

    Recommendations are stored as JSON lists. Each item in the list is a dict:
    {
        "id": "geo_1",
        "layer": "GEO",
        "priority": "high|medium|low",
        "issue": "What's wrong",
        "recommendation": "Specific fix",
        "before": "Current text or 'Not present'",
        "after": "Improved version",
        "field": "content_body|title|meta_description|h1|schema",
        "status": "pending|approved|applied"
    }

    Overall score is the weighted average: GEO 30%, SEO 40%, CRO 30%.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('analyzing', 'Analyzing'),
        ('complete', 'Complete'),
        ('failed', 'Failed'),
    ]

    site = models.ForeignKey(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='page_analyses',
    )
    page_url = models.URLField(max_length=2048)
    page_title = models.CharField(max_length=500, blank=True)

    # ── Input data snapshots ─────────────────────────────────
    gsc_data = models.JSONField(
        default=dict,
        help_text='GSC queries/positions for this page at analysis time',
    )
    wp_meta = models.JSONField(
        default=dict,
        help_text='WordPress page meta: title, h1, meta_description, word_count, schema, content_snippet',
    )

    # ── AI-generated recommendations ─────────────────────────
    geo_recommendations = models.JSONField(default=list)
    seo_recommendations = models.JSONField(default=list)
    cro_recommendations = models.JSONField(default=list)

    # ── Layer scores (0-100) ─────────────────────────────────
    geo_score = models.IntegerField(null=True, blank=True)
    seo_score = models.IntegerField(null=True, blank=True)
    cro_score = models.IntegerField(null=True, blank=True)
    overall_score = models.IntegerField(
        null=True,
        blank=True,
        help_text='Weighted average: GEO 30%, SEO 40%, CRO 30%',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'page_analyses'
        ordering = ['-created_at']
        get_latest_by = 'created_at'
        indexes = [
            models.Index(fields=['site', 'status']),
            models.Index(fields=['site', 'page_url']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"PageAnalysis({self.page_url}) — {self.status}"

    def compute_overall_score(self) -> int:
        """Return weighted average: GEO 30 %, SEO 40 %, CRO 30 %."""
        scores = [
            (self.geo_score, 0.30),
            (self.seo_score, 0.40),
            (self.cro_score, 0.30),
        ]
        weighted = sum(s * w for s, w in scores if s is not None)
        weights = sum(w for s, w in scores if s is not None)
        if not weights:
            return 0
        return round(weighted / weights)
# DOMAIN 6: SILO HEALTH SCORING
# ─────────────────────────────────────────────────────────────

class SiloHealthScore(models.Model):
    """
    Historical snapshot of a silo's health score.

    A new record is written every time recalculation runs (on GSC connect,
    conflict resolution, or on-demand).  The most recent record per silo is
    the "current" score; older records form the history for trend charts.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='silo_health_scores',
    )
    silo = models.ForeignKey(
        SiloDefinition,
        on_delete=models.CASCADE,
        related_name='health_scores',
    )

    # Overall weighted score 0–100
    score = models.DecimalField(max_digits=5, decimal_places=2)

    # Component breakdown — stored as JSON for flexibility
    # {
    #   "keyword_clarity": 82.5,
    #   "structural_integrity": 60.0,
    #   "content_architecture": 75.0,
    #   "internal_linking": 90.0,
    # }
    component_scores = models.JSONField(default=dict)

    # Number of pages in silo at calculation time
    page_count = models.IntegerField(default=0)

    # Optional extra detail (e.g. {"reason": "no_pages_in_silo"})
    details = models.JSONField(default=dict, blank=True)

    # Trigger that caused this calculation
    TRIGGER_CHOICES = [
        ('gsc_connect', 'GSC Connection'),
        ('conflict_resolution', 'Conflict Resolution'),
        ('on_demand', 'On-Demand'),
        ('scheduled', 'Scheduled'),
    ]
    trigger = models.CharField(max_length=30, choices=TRIGGER_CHOICES, default='on_demand')

    calculated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'silo_health_scores'
        ordering = ['-calculated_at']
        indexes = [
            models.Index(fields=['site']),
            models.Index(fields=['silo']),
            models.Index(fields=['site', 'calculated_at']),
            models.Index(fields=['silo', 'calculated_at']),
        ]

    def __str__(self):
        return f"{self.silo.name}: {self.score} @ {self.calculated_at:%Y-%m-%d %H:%M}"
