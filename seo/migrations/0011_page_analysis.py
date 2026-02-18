# Generated migration — PageAnalysis model for Three-Layer Content Optimization

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0010_flip_flop_detection'),
        ('seo', '0010_pageclassification_thin_content'),
        ('sites', '0005_site_gsc_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageAnalysis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_url', models.URLField(max_length=2048)),
                ('page_title', models.CharField(blank=True, max_length=500)),
                ('gsc_data', models.JSONField(default=dict, help_text='GSC queries/positions for this page at analysis time')),
                ('wp_meta', models.JSONField(default=dict, help_text='WordPress page meta: title, h1, meta_description, word_count, schema, content_snippet')),
                ('geo_recommendations', models.JSONField(default=list)),
                ('seo_recommendations', models.JSONField(default=list)),
                ('cro_recommendations', models.JSONField(default=list)),
                ('geo_score', models.IntegerField(blank=True, null=True)),
                ('seo_score', models.IntegerField(blank=True, null=True)),
                ('cro_score', models.IntegerField(blank=True, null=True)),
                ('overall_score', models.IntegerField(blank=True, help_text='Weighted average: GEO 30%, SEO 40%, CRO 30%', null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('analyzing', 'Analyzing'), ('complete', 'Complete'), ('failed', 'Failed')], db_index=True, default='pending', max_length=20)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='page_analyses', to='sites.site')),
            ],
            options={
                'db_table': 'page_analyses',
                'ordering': ['-created_at'],
                'get_latest_by': 'created_at',
                'indexes': [
                    models.Index(fields=['site', 'status'], name='page_analyses_site_status_idx'),
                    models.Index(fields=['site', 'page_url'], name='page_analyses_site_url_idx'),
                    models.Index(fields=['created_at'], name='page_analyses_created_at_idx'),
                ],
            },
        ),
    ]
