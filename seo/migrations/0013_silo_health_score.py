"""
No-op migration: silo_health_scores table was already created by the initial
deployment (0011_silo_health_score from feat/silo-health-v2 branch, applied
during the 2026-02-18 14:28 CT deploy). This migration serves as a checkpoint
so that 0014_page_analysis and 0015_slug_change_log can depend on it.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0012_blog_overlap_count'),
        ('sites', '0005_site_gsc_fields'),
    ]

    operations = [
        # Table already exists from prior deployment — no-op
    ]
