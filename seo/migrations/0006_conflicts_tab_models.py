# Generated migration for conflicts tab models

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0001_initial'),
        ('seo', '0005_page_post_type'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        # Add related_pages field to Page model
        migrations.AddField(
            model_name='page',
            name='related_pages',
            field=models.ManyToManyField(
                blank=True,
                help_text='Pages that support or are supported by this page',
                related_name='related_to_pages',
                symmetrical=False,
                to='seo.page'
            ),
        ),
        
        # Add GSCData model
        migrations.CreateModel(
            name='GSCData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('query', models.CharField(help_text='The search query', max_length=500)),
                ('impressions', models.IntegerField(default=0)),
                ('clicks', models.IntegerField(default=0)),
                ('position', models.FloatField(default=0)),
                ('ctr', models.FloatField(default=0)),
                ('date_start', models.DateField()),
                ('date_end', models.DateField()),
                ('device', models.CharField(blank=True, help_text='Device type: desktop, mobile, tablet', max_length=20)),
                ('country', models.CharField(blank=True, help_text='Country code', max_length=2)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('page', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='gsc_data', to='seo.page')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='gsc_data', to='sites.site')),
            ],
            options={
                'db_table': 'gsc_data',
                'ordering': ['-impressions', '-clicks'],
                'indexes': [
                    models.Index(fields=['page', 'query'], name='seo_gscda_page_id_8c0f1a_idx'),
                    models.Index(fields=['site', 'query'], name='seo_gscda_site_id_5c3f2a_idx'),
                    models.Index(fields=['impressions'], name='seo_gscda_impress_2859f3_idx'),
                    models.Index(fields=['position'], name='seo_gscda_positio_4e7b1c_idx'),
                ],
            },
        ),
        
        # Add Conflict model
        migrations.CreateModel(
            name='Conflict',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('query_string', models.CharField(help_text='The GSC query string these pages compete for', max_length=500)),
                ('location_differentiation', models.JSONField(default=list, help_text='Location-based differentiation data')),
                ('recommendation', models.TextField(blank=True, help_text='AI-generated recommendation for resolving this conflict')),
                ('status', models.CharField(choices=[('active', 'Active'), ('in_approval_queue', 'In Approval Queue'), ('resolved', 'Resolved')], default='active', max_length=20)),
                ('is_dismissed', models.BooleanField(default=False)),
                ('severity_score', models.IntegerField(default=50, help_text='Severity score (0-100)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('page1', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conflicts_as_page1', to='seo.page')),
                ('page2', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conflicts_as_page2', to='seo.page')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conflicts', to='sites.site')),
                ('winner_page', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='won_conflicts', to='seo.page')),
            ],
            options={
                'db_table': 'conflicts',
                'ordering': ['-severity_score', '-created_at'],
                'unique_together': [['site', 'page1', 'page2', 'query_string']],
                'indexes': [
                    models.Index(fields=['site', 'status'], name='seo_confli_site_id_6f3a2b_idx'),
                    models.Index(fields=['query_string'], name='seo_confli_query_s_7d4e1c_idx'),
                    models.Index(fields=['severity_score'], name='seo_confli_severit_9a2f3d_idx'),
                ],
            },
        ),
        
        # Add ContentJob model
        migrations.CreateModel(
            name='ContentJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_type', models.CharField(choices=[('conflict_resolution', 'Conflict Resolution'), ('supporting_content', 'Supporting Content'), ('money_page_optimization', 'Money Page Optimization'), ('homepage_optimization', 'Homepage Optimization')], max_length=50)),
                ('topic', models.CharField(blank=True, max_length=500)),
                ('recommendation', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('pending_approval', 'Pending Approval'), ('approved', 'Approved'), ('in_progress', 'In Progress'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('priority', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], default='medium', max_length=10)),
                ('estimated_word_count', models.IntegerField(blank=True, null=True)),
                ('actual_word_count', models.IntegerField(blank=True, null=True)),
                ('generated_content', models.TextField(blank=True)),
                ('wp_post_id', models.IntegerField(blank=True, null=True)),
                ('wp_status', models.CharField(blank=True, max_length=20)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_content_jobs', to='auth.user')),
                ('conflict', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_jobs', to='seo.conflict')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='auth.user')),
                ('page', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='content_jobs', to='seo.page')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_jobs', to='sites.site')),
                ('target_page', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='targeted_content_jobs', to='seo.page')),
            ],
            options={
                'db_table': 'content_jobs',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['site', 'status'], name='seo_conten_site_id_3e8b2a_idx'),
                    models.Index(fields=['job_type'], name='seo_conten_job_typ_7c4f1d_idx'),
                    models.Index(fields=['priority'], name='seo_conten_priorit_9a2e3f_idx'),
                    models.Index(fields=['created_at'], name='seo_conten_create_8d5f4b_idx'),
                ],
            },
        ),
    ]
