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
