"""
Page and SEO metrics models.
"""
from django.db import models
from sites.models import Site


class Page(models.Model):
    """
    Represents a WordPress page/post synced from WordPress.
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='pages'
    )
    wp_post_id = models.IntegerField(
        help_text="WordPress post/page ID"
    )
    url = models.URLField()
    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500)
    content = models.TextField(blank=True)
    excerpt = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        default='publish',
        choices=[
            ('publish', 'Published'),
            ('draft', 'Draft'),
            ('private', 'Private'),
        ]
    )
    published_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    parent_id = models.IntegerField(null=True, blank=True)
    menu_order = models.IntegerField(default=0)
    
    # WordPress metadata
    yoast_title = models.CharField(max_length=500, blank=True)
    yoast_description = models.TextField(blank=True)
    featured_image = models.URLField(blank=True)
    
    # Siloq metadata
    siloq_page_id = models.CharField(max_length=255, blank=True, null=True)
    is_money_page = models.BooleanField(default=False, help_text="Is this a money/target page?")
    is_homepage = models.BooleanField(default=False, help_text="Is this the homepage?")
    is_noindex = models.BooleanField(default=False, help_text="Is this page set to noindex?")
    
    # Silo assignment (which money page this supports)
    parent_silo = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supporting_pages',
        help_text="The money page this supporting page belongs to"
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
        ]

    def __str__(self):
        return f"{self.title} ({self.site.name})"
    
    @property
    def page_type(self):
        """Return the page type for visualization."""
        if self.is_homepage:
            return 'homepage'
        elif self.is_money_page:
            return 'target'
        elif self.parent_silo:
            return 'supporting'
        return 'unassigned'


class InternalLink(models.Model):
    """
    Represents an internal link between two pages.
    Stores the source page, target page, anchor text, and context.
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='internal_links'
    )
    source_page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='outgoing_links',
        help_text="The page containing the link"
    )
    target_page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='incoming_links',
        null=True,
        blank=True,
        help_text="The page being linked to (null if external or not found)"
    )
    target_url = models.URLField(
        help_text="The URL being linked to"
    )
    anchor_text = models.CharField(
        max_length=500,
        blank=True,
        help_text="The clickable text of the link"
    )
    anchor_text_normalized = models.CharField(
        max_length=500,
        blank=True,
        help_text="Lowercase, stripped anchor text for comparison"
    )
    
    # Link context
    context_text = models.TextField(
        blank=True,
        help_text="Surrounding text for context (±50 chars)"
    )
    is_in_content = models.BooleanField(
        default=True,
        help_text="Is this link in main content (vs nav/footer)?"
    )
    is_nofollow = models.BooleanField(
        default=False,
        help_text="Does this link have rel=nofollow?"
    )
    
    # Analysis flags
    is_valid = models.BooleanField(
        default=True,
        help_text="Is this a valid internal link?"
    )
    
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
        # Normalize anchor text for comparison
        if self.anchor_text:
            self.anchor_text_normalized = self.anchor_text.lower().strip()
        super().save(*args, **kwargs)


class AnchorTextConflict(models.Model):
    """
    Tracks anchor text conflicts where the same anchor links to different pages.
    This is a governance issue - same keyword shouldn't point to multiple targets.
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='anchor_conflicts'
    )
    anchor_text = models.CharField(
        max_length=500,
        help_text="The conflicting anchor text"
    )
    anchor_text_normalized = models.CharField(
        max_length=500,
        help_text="Lowercase normalized anchor"
    )
    
    # The pages this anchor points to (should only be ONE)
    conflicting_pages = models.ManyToManyField(
        Page,
        related_name='anchor_conflicts',
        help_text="Pages this anchor text links to"
    )
    
    occurrence_count = models.IntegerField(
        default=0,
        help_text="How many times this anchor appears across the site"
    )
    
    severity = models.CharField(
        max_length=20,
        choices=[
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low'),
        ],
        default='medium'
    )
    
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
    """
    Tracks internal linking issues for governance.
    """
    ISSUE_TYPES = [
        ('anchor_conflict', 'Anchor Text Conflict'),
        ('homepage_theft', 'Homepage Anchor Theft'),
        ('missing_target_link', 'Missing Link to Target'),
        ('missing_sibling_links', 'Missing Sibling Links'),
        ('orphan_page', 'Orphan Page'),
        ('cross_silo_link', 'Cross-Silo Link'),
        ('too_many_supporting', 'Too Many Supporting Pages'),
    ]
    
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='link_issues'
    )
    issue_type = models.CharField(
        max_length=50,
        choices=ISSUE_TYPES
    )
    severity = models.CharField(
        max_length=20,
        choices=[
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low'),
        ],
        default='medium'
    )
    
    # Affected page(s)
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='link_issues',
        null=True,
        blank=True
    )
    related_pages = models.ManyToManyField(
        Page,
        related_name='related_link_issues',
        blank=True
    )
    
    # Issue details
    description = models.TextField()
    recommendation = models.TextField(blank=True)
    
    # For anchor conflicts
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
    """
    SEO metrics and analysis data for a page.
    Stores comprehensive SEO information including titles, meta descriptions,
    headings, links, images, and identified issues.
    """
    page = models.OneToOneField(
        Page,
        on_delete=models.CASCADE,
        related_name='seo_data'
    )
    
    # Basic SEO elements
    meta_title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(blank=True)
    meta_keywords = models.CharField(max_length=500, blank=True)
    
    # Headings structure
    h1_count = models.IntegerField(default=0)
    h1_text = models.CharField(max_length=500, blank=True)
    h2_count = models.IntegerField(default=0)
    h2_texts = models.JSONField(
        default=list,
        help_text="List of H2 headings"
    )
    h3_count = models.IntegerField(default=0)
    h3_texts = models.JSONField(
        default=list,
        help_text="List of H3 headings"
    )
    
    # Links analysis
    internal_links_count = models.IntegerField(default=0)
    external_links_count = models.IntegerField(default=0)
    internal_links = models.JSONField(
        default=list,
        help_text="List of internal link URLs"
    )
    external_links = models.JSONField(
        default=list,
        help_text="List of external link URLs"
    )
    
    # Images analysis
    images_count = models.IntegerField(default=0)
    images_without_alt = models.IntegerField(default=0)
    images = models.JSONField(
        default=list,
        help_text="List of image URLs and alt texts"
    )
    
    # Content analysis
    word_count = models.IntegerField(default=0)
    reading_time_minutes = models.FloatField(default=0)
    
    # SEO Score and Issues
    seo_score = models.IntegerField(
        default=0,
        help_text="Overall SEO score (0-100)"
    )
    issues = models.JSONField(
        default=list,
        help_text="List of SEO issues found, e.g. [{'type': 'missing_meta_description', 'severity': 'high', 'message': '...'}]"
    )
    recommendations = models.JSONField(
        default=list,
        help_text="List of SEO recommendations"
    )
    
    # Technical SEO
    has_canonical = models.BooleanField(default=False)
    canonical_url = models.URLField(blank=True)
    has_schema = models.BooleanField(default=False)
    schema_type = models.CharField(max_length=100, blank=True)
    
    # Scan metadata
    scanned_at = models.DateTimeField(auto_now_add=True)
    scan_version = models.CharField(max_length=50, default='1.0')
    
    class Meta:
        db_table = 'seo_data'
        ordering = ['-scanned_at']

    def __str__(self):
        return f"SEO Data for {self.page.title}"
