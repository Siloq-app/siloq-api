# Simplified migration — only creates SiteIntelligence model.
# All index renames and field cleanups removed because prod DB state
# does not match expected pre-conditions for those operations.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0025_merge_gsc_conflicts'),
        ('sites', '0008_site_intelligence'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteIntelligence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('business_type', models.CharField(default='general', max_length=50)),
                ('primary_goal', models.TextField(blank=True)),
                ('raw_analysis', models.JSONField(default=dict)),
                ('hub_pages', models.JSONField(default=list)),
                ('spoke_pages', models.JSONField(default=list)),
                ('orphan_pages', models.JSONField(default=list)),
                ('architecture_problems', models.JSONField(default=list)),
                ('content_gaps', models.JSONField(default=list)),
                ('cannibalization_risks', models.JSONField(default=list)),
                ('generated_at', models.DateTimeField(auto_now=True)),
                ('generation_error', models.TextField(blank=True)),
                ('site', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='intelligence', to='sites.site')),
            ],
        ),
    ]
