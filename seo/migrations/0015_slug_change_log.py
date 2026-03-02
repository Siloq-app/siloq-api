# Generated migration for SlugChangeLog model

import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0014_page_analysis'),
        ('sites', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SlugChangeLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('page_id', models.IntegerField(help_text='WordPress post/page ID')),
                ('old_url', models.CharField(max_length=2048)),
                ('old_slug', models.CharField(max_length=500)),
                ('new_url', models.CharField(max_length=2048)),
                ('new_slug', models.CharField(max_length=500)),
                ('redirect_status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('created', 'Created'),
                        ('failed', 'Failed'),
                        ('verified', 'Verified'),
                    ],
                    default='pending',
                    max_length=20
                )),
                ('slug_change_status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('completed', 'Completed'),
                        ('failed', 'Failed'),
                        ('rolled_back', 'Rolled Back'),
                    ],
                    default='pending',
                    max_length=20
                )),
                ('reason', models.CharField(default='seo_optimization', max_length=100)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('changed_by', models.CharField(default='siloq_system', max_length=255)),
                ('changed_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('redirect', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='slug_changes',
                    to='seo.redirectregistry'
                )),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='slug_changes',
                    to='sites.site'
                )),
            ],
            options={
                'db_table': 'slug_change_log',
                'indexes': [
                    models.Index(fields=['site'], name='slug_change_site_idx'),
                    models.Index(fields=['page_id'], name='slug_change_page_idx'),
                    models.Index(fields=['site', 'page_id'], name='slug_change_site_page_idx'),
                    models.Index(fields=['old_url'], name='slug_change_old_url_idx'),
                    models.Index(fields=['new_url'], name='slug_change_new_url_idx'),
                    models.Index(fields=['changed_at'], name='slug_change_changed_at_idx'),
                ],
            },
        ),
    ]
