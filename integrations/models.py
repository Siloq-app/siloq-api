"""
Models for WordPress integrations and scans.
"""
from django.db import models
from sites.models import Site, APIKey


class Scan(models.Model):
    """
    Represents a website scan initiated from WordPress lead gen scanner.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='scans',
        null=True,
        blank=True
    )
    scan_type = models.CharField(
        max_length=50,
        default='full',
        choices=[
            ('full', 'Full Scan'),
            ('quick', 'Quick Scan'),
        ]
    )
    url = models.URLField(help_text="URL being scanned")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Scan results
    score = models.IntegerField(null=True, blank=True, help_text="Overall SEO score (0-100)")
    pages_analyzed = models.IntegerField(default=0)
    scan_duration_seconds = models.FloatField(null=True, blank=True)
    
    # Detailed results (stored as JSON)
    results = models.JSONField(
        default=dict,
        help_text="Detailed scan results including scores, issues, recommendations"
    )
    
    # Error handling
    error_message = models.TextField(blank=True)
    
    # Metadata
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'scans'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['status', 'started_at']),
            models.Index(fields=['url']),
        ]

    def __str__(self):
        return f"Scan {self.id} - {self.url} ({self.status})"
