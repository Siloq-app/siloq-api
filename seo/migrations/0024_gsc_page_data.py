"""
Create SiteGSCPageData table for persisting per-page GSC performance data.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0006_site_gbp_fields'),
        ('seo', '0023_page_junk_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteGSCPageData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url', models.URLField(max_length=2048)),
                ('impressions_28d', models.IntegerField(default=0)),
                ('clicks_28d', models.IntegerField(default=0)),
                ('avg_position', models.FloatField(blank=True, null=True)),
                ('top_queries', models.JSONField(default=list)),
                ('synced_at', models.DateTimeField(auto_now=True)),
                ('page', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='gsc_page_data', to='seo.page')),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='gsc_pages', to='sites.site')),
            ],
            options={
                'db_table': 'seo_gsc_page_data',
                'unique_together': {('site', 'url')},
            },
        ),
    ]
