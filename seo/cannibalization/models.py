"""
Django models for cannibalization detection.
Stores analysis runs, clusters, and page classifications.
"""
from django.db import models
from django.utils import timezone
from sites.models import Site


class AnalysisRun(models.Model):
    """
    Tracks a single cannibalization analysis run for a site.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='cannibalization_runs'
    )
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    
    # Run metadata
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # GSC connection
    gsc_connected = models.BooleanField(
        default=False,
        help_text="Was GSC data available for this run?"
    )
    gsc_date_start = models.DateField(null=True, blank=True)
    gsc_date_end = models.DateField(null=True, blank=True)
    
    # Results summary
    total_pages_analyzed = models.IntegerField(default=0)
    total_clusters_found = models.IntegerField(default=0)
    
    # Bucket counts
    search_conflict_count = models.IntegerField(
        default=0,
        help_text="SEARCH_CONFLICT bucket count"
    )
    site_duplication_count = models.IntegerField(
        default=0,
        help_text="SITE_DUPLICATION bucket count"
    )
    wrong_winner_count = models.IntegerField(
        default=0,
        help_text="WRONG_WINNER bucket count"
    )
    
    # Badge counts
    confirmed_count = models.IntegerField(
        default=0,
        help_text="GSC-confirmed conflicts"
    )
    potential_count = models.IntegerField(
        default=0,
        help_text="Static detection (not GSC-validated)"
    )
    wrong_winner_badge_count = models.IntegerField(
        default=0,
        help_text="Wrong winner detections"
    )
    
    # Error tracking
    error_message = models.TextField(blank=True)
    
    class Meta:
        db_table = 'cannibalization_analysis_runs'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['site', '-started_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"Analysis Run for {self.site.name} - {self.started_at.strftime('%Y-%m-%d %H:%M')}"
    
    def mark_completed(self):
        """Mark the run as completed."""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()
    
    def mark_failed(self, error_msg: str):
        """Mark the run as failed with error message."""
        self.status = 'failed'
        self.error_message = error_msg
        self.completed_at = timezone.now()
        self.save()


class ClusterResult(models.Model):
    """
    A single cannibalization cluster (group of conflicting pages).
    """
    SEVERITY_CHOICES = [
        ('SEVERE', 'Severe'),
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'),
        ('LOW', 'Low'),
    ]
    
    BUCKET_CHOICES = [
        ('SEARCH_CONFLICT', 'Search Conflict'),
        ('SITE_DUPLICATION', 'Site Duplication'),
        ('WRONG_WINNER', 'Wrong Winner'),
    ]
    
    BADGE_CHOICES = [
        ('CONFIRMED', 'Confirmed'),
        ('POTENTIAL', 'Potential'),
        ('WRONG_WINNER', 'Wrong Winner'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('resolved', 'Resolved'),
        ('ignored', 'Ignored'),
    ]
    
    analysis_run = models.ForeignKey(
        AnalysisRun,
        on_delete=models.CASCADE,
        related_name='clusters'
    )
    
    # Cluster identification
    cluster_key = models.CharField(
        max_length=500,
        help_text="Unique key for grouping (conflict_type:keyword)"
    )
    
    # Classification
    bucket = models.CharField(max_length=50, choices=BUCKET_CHOICES)
    badge = models.CharField(max_length=50, choices=BADGE_CHOICES)
    conflict_type = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    
    # Action
    action_code = models.CharField(max_length=100)
    
    # Priority scoring
    priority_score = models.IntegerField(
        default=0,
        help_text="Calculated priority: bucket(50) + severity(30) + impressions(20)"
    )
    
    # Pages involved
    page_count = models.IntegerField(default=0)
    pages_json = models.JSONField(
        default=list,
        help_text="List of page objects with URL, title, type, etc."
    )
    
    # GSC data (if available)
    gsc_query = models.CharField(
        max_length=500,
        blank=True,
        help_text="Search query triggering conflict"
    )
    gsc_total_impressions = models.IntegerField(
        default=0,
        help_text="Total impressions across all pages"
    )
    gsc_total_clicks = models.IntegerField(
        default=0,
        help_text="Total clicks across all pages"
    )
    gsc_data_json = models.JSONField(
        default=dict,
        help_text="Full GSC data: impression shares, positions, etc."
    )
    
    # Recommendations
    recommendation = models.TextField(blank=True)
    suggested_canonical_url = models.URLField(blank=True)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'cannibalization_clusters'
        ordering = ['-priority_score', '-created_at']
        indexes = [
            models.Index(fields=['analysis_run', '-priority_score']),
            models.Index(fields=['bucket']),
            models.Index(fields=['badge']),
            models.Index(fields=['status']),
            models.Index(fields=['cluster_key']),
        ]
    
    def __str__(self):
        return f"{self.conflict_type} - {self.cluster_key[:50]}"


class PageClassification(models.Model):
    """
    Stores the classification result for each page in an analysis run.
    This is the output of Phase 1.
    """
    analysis_run = models.ForeignKey(
        AnalysisRun,
        on_delete=models.CASCADE,
        related_name='page_classifications'
    )
    
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='page_classifications'
    )
    
    # Page reference (we don't FK to Page because pages might be deleted)
    page_id = models.IntegerField(help_text="Reference to Page.id")
    url = models.URLField()
    title = models.CharField(max_length=500)
    
    # Phase 1 output
    normalized_url = models.CharField(max_length=1000)
    normalized_path = models.CharField(max_length=1000)
    classified_type = models.CharField(
        max_length=50,
        help_text="homepage, location, blog, product, category_woo, shop_root, etc."
    )
    is_legacy_variant = models.BooleanField(default=False)
    
    # Parsed metadata
    folder_root = models.CharField(max_length=100, blank=True)
    parent_path = models.CharField(max_length=1000, blank=True)
    slug_last = models.CharField(max_length=500, blank=True)
    depth = models.IntegerField(default=0)
    
    # Geographic extraction (for location pages)
    geo_node = models.CharField(max_length=200, blank=True)
    
    # Service extraction (for service/location pages)
    service_keyword = models.CharField(max_length=200, blank=True)
    
    # Slug tokens (for comparison)
    slug_tokens_json = models.JSONField(
        default=list,
        help_text="List of slug tokens for similarity comparison"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'cannibalization_page_classifications'
        ordering = ['classified_type', 'normalized_path']
        indexes = [
            models.Index(fields=['analysis_run', 'classified_type']),
            models.Index(fields=['site', 'analysis_run']),
            models.Index(fields=['folder_root']),
            models.Index(fields=['is_legacy_variant']),
        ]
        unique_together = [['analysis_run', 'page_id']]
    
    def __str__(self):
        return f"{self.classified_type}: {self.title}"
