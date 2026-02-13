"""
AI Content Engine models.
Stores system prompts and generated plans.
"""
from django.db import models
from sites.models import Site


class SystemPrompt(models.Model):
    """
    Versioned system prompts for AI content generation.
    Keys: merge_plan, spoke_rewrite, merge_draft, spoke_draft
    """
    prompt_key = models.CharField(max_length=50, unique=True)
    prompt_text = models.TextField()
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ai_system_prompts'

    def __str__(self):
        return f"{self.prompt_key} v{self.version}"


class GeneratedPlan(models.Model):
    """
    Stores AI-generated plans (merge plans, spoke rewrites, drafts).
    """
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='ai_plans'
    )
    conflict_id = models.IntegerField(
        help_text="ClusterResult ID that triggered this plan"
    )
    conflict_query = models.CharField(max_length=500)
    action = models.CharField(max_length=50)
    prompt_version = models.IntegerField()
    context_payload = models.JSONField()
    ai_response = models.JSONField()
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_generated_plans'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} for '{self.conflict_query}' ({self.created_at})"
