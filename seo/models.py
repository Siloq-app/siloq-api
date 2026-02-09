"""
Page and SEO metrics models.
Includes cannibalization detection, topic clusters, reverse silos, and pending actions.
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
        ]

    def __str__(self):
        return f"{self.title} ({self.site.name})"


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
        help_text="List of SEO issues found"
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


class TopicCluster(models.Model):
    """
    A group of semantically related entities that define a content topic.
    Used to organize content into logical groupings.
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='topic_clusters'
    )
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'seo_topic_clusters'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.site.name})"


class CannibalizationIssue(models.Model):
    """
    Represents a keyword cannibalization issue where multiple pages
    compete for the same keyword, splitting ranking signals.
    """
    SEVERITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    RECOMMENDATION_CHOICES = [
        ('consolidate', 'Consolidate'),
        ('differentiate', 'Differentiate'),
        ('redirect', 'Redirect'),
    ]
    
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='cannibalization_issues'
    )
    keyword = models.CharField(max_length=500)
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default='medium'
    )
    recommendation_type = models.CharField(
        max_length=50,
        choices=RECOMMENDATION_CHOICES,
        null=True,
        blank=True
    )
    total_impressions = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total monthly impressions from GSC (if connected)"
    )
    recommended_target_page = models.ForeignKey(
        Page,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recommended_for_issues',
        help_text="The suggested 'King' page that should win"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'seo_cannibalization_issues'
        ordering = ['-created_at']
        verbose_name_plural = 'Cannibalization issues'

    def __str__(self):
        return f"Cannibalization: {self.keyword} ({self.severity})"


class CannibalizationIssuePage(models.Model):
    """
    Junction table linking cannibalization issues to the competing pages.
    """
    issue = models.ForeignKey(
        CannibalizationIssue,
        on_delete=models.CASCADE,
        related_name='competing_pages'
    )
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='cannibalization_issues'
    )
    impression_share = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Percentage of impressions this page receives"
    )
    order = models.IntegerField(
        default=0,
        help_text="Display order (0 = highest performer)"
    )

    class Meta:
        db_table = 'seo_cannibalization_issue_pages'
        ordering = ['order']
        unique_together = [['issue', 'page']]

    def __str__(self):
        return f"{self.issue.keyword} -> {self.page.title}"


class ReverseSilo(models.Model):
    """
    A Reverse Silo (content architecture) where Supporting Pages
    link UP to a Target Page, concentrating authority.
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='reverse_silos'
    )
    name = models.CharField(max_length=255)
    target_page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='silos_as_target',
        help_text="The Target (Money) Page that receives links"
    )
    topic_cluster = models.ForeignKey(
        TopicCluster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='silos'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'seo_reverse_silos'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} -> {self.target_page.title}"


class ReverseSiloSupporting(models.Model):
    """
    Junction table linking Supporting Pages to their Reverse Silo.
    """
    silo = models.ForeignKey(
        ReverseSilo,
        on_delete=models.CASCADE,
        related_name='supporting_pages'
    )
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='silos_as_supporting'
    )
    order = models.IntegerField(
        default=0,
        help_text="Display order within the silo"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'seo_reverse_silo_supporting'
        ordering = ['order']
        unique_together = [['silo', 'page']]

    def __str__(self):
        return f"{self.silo.name} <- {self.page.title}"


class PendingAction(models.Model):
    """
    A recommended action from Siloq that requires user approval.
    Tracks remediation steps for cannibalization, linking, and content issues.
    """
    ACTION_TYPE_CHOICES = [
        ('generate_content', 'Generate Supporting Content'),
        ('differentiate', 'Differentiate Competing Page'),
        ('consolidate', 'Consolidate Pages'),
        ('redirect', 'Redirect & Archive'),
        ('add_link', 'Add Internal Link'),
        ('remove_link', 'Remove Internal Link'),
        ('reassign_keyword', 'Reassign Primary Keyword'),
        ('restructure_silo', 'Restructure Silo'),
    ]
    
    RISK_CHOICES = [
        ('safe', 'Safe'),
        ('moderate', 'Moderate'),
        ('high', 'High'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
        ('executed', 'Executed'),
        ('rolled_back', 'Rolled Back'),
    ]
    
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='pending_actions'
    )
    action_type = models.CharField(
        max_length=50,
        choices=ACTION_TYPE_CHOICES
    )
    description = models.TextField(
        help_text="Human-readable description of the change"
    )
    risk = models.CharField(
        max_length=20,
        choices=RISK_CHOICES,
        default='safe'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    impact = models.TextField(
        blank=True,
        help_text="Expected outcome of the action"
    )
    doctrine = models.CharField(
        max_length=100,
        blank=True,
        help_text="The Siloq doctrine rule that triggered this action"
    )
    related_issue = models.ForeignKey(
        CannibalizationIssue,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_actions'
    )
    related_silo = models.ForeignKey(
        ReverseSilo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_actions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    rollback_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Data needed to rollback this action"
    )
    rollback_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="48-hour window for rollback"
    )

    class Meta:
        db_table = 'seo_pending_actions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_action_type_display()}: {self.description[:50]}"

    @property
    def is_destructive(self):
        """Returns True if this action type is destructive."""
        destructive_types = ['consolidate', 'redirect', 'reassign_keyword', 'restructure_silo']
        return self.action_type in destructive_types
