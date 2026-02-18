"""
Migration: Add SiloHealthScore model — 4-component weighted silo health scoring.
Matches seo/models.py SiloHealthScore definition from feat/silo-health-v2.
"""
import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0012_blog_overlap_count'),
        ('sites', '0005_site_gsc_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiloHealthScore',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('health_score', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('internal_link_density_score', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('keyword_coherence_score', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('content_coverage_score', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('conflict_ratio_score', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('total_pages', models.IntegerField(default=0)),
                ('total_internal_links', models.IntegerField(default=0)),
                ('ideal_internal_links', models.IntegerField(default=0)),
                ('unique_keywords', models.IntegerField(default=0)),
                ('competing_keywords', models.IntegerField(default=0)),
                ('expected_subtopics', models.IntegerField(default=0)),
                ('covered_subtopics', models.IntegerField(default=0)),
                ('open_conflicts', models.IntegerField(default=0)),
                ('resolved_conflicts', models.IntegerField(default=0)),
                ('health_status', models.CharField(
                    choices=[('excellent', 'Excellent'),('good', 'Good'),('fair', 'Fair'),('poor', 'Poor'),('critical', 'Critical'),('unknown', 'Unknown')],
                    default='unknown', max_length=20,
                )),
                ('recommended_actions', models.JSONField(blank=True, default=list)),
                ('previous_score', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('score_change', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('scored_at', models.DateTimeField(auto_now_add=True)),
                ('calculation_metadata', models.JSONField(blank=True, default=dict)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='silo_health_scores', to='sites.site')),
                ('silo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='health_scores', to='seo.silodefinition')),
            ],
            options={
                'db_table': 'silo_health_scores',
                'ordering': ['-scored_at'],
                'indexes': [
                    models.Index(fields=['site', 'silo'], name='silo_health_site_silo_idx'),
                    models.Index(fields=['site', 'scored_at'], name='silo_health_site_scored_idx'),
                    models.Index(fields=['health_status'], name='silo_health_status_idx'),
                    models.Index(fields=['scored_at'], name='silo_health_scored_at_idx'),
                ],
            },
        ),
    ]
