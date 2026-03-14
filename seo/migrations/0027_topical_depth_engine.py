"""
Migration: Topical Depth & Semantic Closure Engine — 5 new tables.

Tables: silo_topic_boundaries, subtopic_map, silo_depth_scores,
        semantic_link_relationships, content_decay_log.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0001_initial'),
        ('seo', '0026_site_intelligence'),
        ('seo', '0026_siteaudit'),
    ]

    operations = [
        # ── 1. silo_topic_boundaries ─────────────────────────────
        migrations.CreateModel(
            name='SiloTopicBoundary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('core_topic', models.CharField(max_length=255)),
                ('adjacent_topics', models.JSONField(default=list)),
                ('out_of_scope_topics', models.JSONField(default=list)),
                ('entity_type_override', models.CharField(
                    blank=True,
                    choices=[
                        ('local_business', 'Local Business'),
                        ('ecommerce', 'E-Commerce'),
                        ('publisher', 'Publisher'),
                        ('b2b', 'B2B / SaaS'),
                    ],
                    max_length=20,
                    null=True,
                )),
                ('defined_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='topic_boundaries',
                    to='sites.site',
                )),
                ('silo', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='topic_boundary',
                    to='seo.silodefinition',
                )),
            ],
            options={
                'db_table': 'silo_topic_boundaries',
                'unique_together': {('site', 'silo')},
            },
        ),
        migrations.AddIndex(
            model_name='silotopicboundary',
            index=models.Index(fields=['silo'], name='silo_topic__silo_id_idx'),
        ),

        # ── 2. subtopic_map ──────────────────────────────────────
        migrations.CreateModel(
            name='SubtopicMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subtopic_slug', models.CharField(max_length=255)),
                ('subtopic_label', models.CharField(max_length=255)),
                ('subtopic_type', models.CharField(
                    choices=[
                        ('core', 'Core'),
                        ('supporting', 'Supporting'),
                        ('adjacent', 'Adjacent'),
                        ('edge_case', 'Edge Case'),
                        ('comparative', 'Comparative'),
                        ('evidence', 'Evidence'),
                    ],
                    default='supporting',
                    max_length=20,
                )),
                ('coverage_status', models.CharField(
                    choices=[
                        ('covered', 'Covered'),
                        ('thin', 'Thin'),
                        ('missing', 'Missing'),
                        ('stale', 'Stale'),
                    ],
                    default='missing',
                    max_length=10,
                )),
                ('priority_score', models.IntegerField(default=50)),
                ('search_demand_signal', models.CharField(blank=True, max_length=50, null=True)),
                ('last_assessed', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subtopic_maps',
                    to='sites.site',
                )),
                ('silo', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='subtopic_maps',
                    to='seo.silodefinition',
                )),
                ('mapped_page', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='subtopic_mappings',
                    to='seo.page',
                )),
            ],
            options={
                'db_table': 'subtopic_map',
                'unique_together': {('silo', 'subtopic_slug')},
            },
        ),
        migrations.AddIndex(
            model_name='subtopicmap',
            index=models.Index(fields=['silo'], name='subtopic_ma_silo_id_idx'),
        ),
        migrations.AddIndex(
            model_name='subtopicmap',
            index=models.Index(fields=['silo', 'coverage_status'], name='subtopic_ma_silo_cov_idx'),
        ),
        migrations.AddIndex(
            model_name='subtopicmap',
            index=models.Index(fields=['silo', '-priority_score'], name='subtopic_ma_silo_pri_idx'),
        ),

        # ── 3. silo_depth_scores ─────────────────────────────────
        migrations.CreateModel(
            name='SiloDepthScore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('semantic_density_score', models.IntegerField(default=0)),
                ('topical_closure_score', models.IntegerField(default=0)),
                ('coverage_breadth_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('coverage_depth_pct', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('thin_page_count', models.IntegerField(default=0)),
                ('missing_subtopic_count', models.IntegerField(default=0)),
                ('stale_page_count', models.IntegerField(default=0)),
                ('scope_creep_flag', models.BooleanField(default=False)),
                ('disconnected_page_count', models.IntegerField(default=0)),
                ('freshness_score', models.IntegerField(default=0)),
                ('depth_mistake_flags', models.JSONField(default=list)),
                ('scored_at', models.DateTimeField(auto_now_add=True)),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='depth_scores',
                    to='sites.site',
                )),
                ('silo', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='depth_scores',
                    to='seo.silodefinition',
                )),
            ],
            options={
                'db_table': 'silo_depth_scores',
            },
        ),
        migrations.AddIndex(
            model_name='silodepthscore',
            index=models.Index(fields=['silo'], name='silo_depth__silo_id_idx'),
        ),
        migrations.AddIndex(
            model_name='silodepthscore',
            index=models.Index(fields=['silo', '-scored_at'], name='silo_depth__silo_scored_idx'),
        ),

        # ── 4. semantic_link_relationships ───────────────────────
        migrations.CreateModel(
            name='SemanticLinkRelationship',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('relationship_type', models.CharField(
                    choices=[
                        ('hierarchical', 'Hierarchical'),
                        ('sequential', 'Sequential'),
                        ('comparative', 'Comparative'),
                        ('complementary', 'Complementary'),
                        ('prerequisite', 'Prerequisite'),
                        ('evidence', 'Evidence'),
                        ('unclassified', 'Unclassified'),
                    ],
                    default='unclassified',
                    max_length=20,
                )),
                ('anchor_text', models.CharField(blank=True, max_length=500)),
                ('anchor_context', models.TextField(blank=True)),
                ('relationship_confidence', models.CharField(
                    choices=[('high', 'High'), ('medium', 'Medium'), ('low', 'Low')],
                    default='low',
                    max_length=10,
                )),
                ('assessed_at', models.DateTimeField(auto_now_add=True)),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='semantic_link_relationships',
                    to='sites.site',
                )),
                ('source_page', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='semantic_links_out',
                    to='seo.page',
                )),
                ('target_page', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='semantic_links_in',
                    to='seo.page',
                )),
            ],
            options={
                'db_table': 'semantic_link_relationships',
                'unique_together': {('source_page', 'target_page')},
            },
        ),
        migrations.AddIndex(
            model_name='semanticlinkrelationship',
            index=models.Index(fields=['site'], name='sem_link_site_idx'),
        ),
        migrations.AddIndex(
            model_name='semanticlinkrelationship',
            index=models.Index(fields=['source_page'], name='sem_link_source_idx'),
        ),
        migrations.AddIndex(
            model_name='semanticlinkrelationship',
            index=models.Index(fields=['site', 'relationship_type'], name='sem_link_site_type_idx'),
        ),

        # ── 5. content_decay_log ─────────────────────────────────
        migrations.CreateModel(
            name='ContentDecayLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_modified', models.DateField(blank=True, null=True)),
                ('days_since_update', models.IntegerField(blank=True, null=True)),
                ('decay_severity', models.CharField(
                    choices=[('warning', 'Warning'), ('critical', 'Critical')],
                    max_length=10,
                )),
                ('flagged_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='decay_logs',
                    to='sites.site',
                )),
                ('page', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='decay_logs',
                    to='seo.page',
                )),
                ('silo', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='decay_logs',
                    to='seo.silodefinition',
                )),
            ],
            options={
                'db_table': 'content_decay_log',
            },
        ),
        migrations.AddIndex(
            model_name='contentdecaylog',
            index=models.Index(fields=['site'], name='decay_log_site_idx'),
        ),
        migrations.AddIndex(
            model_name='contentdecaylog',
            index=models.Index(fields=['page'], name='decay_log_page_idx'),
        ),
    ]
