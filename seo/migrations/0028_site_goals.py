from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0027_merge_0026_conflicts'),
        ('sites', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteGoals',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('primary_goal', models.CharField(
                    choices=[
                        ('local_leads', 'Local Leads'),
                        ('ecommerce_sales', 'E-commerce Sales'),
                        ('topic_authority', 'Topic Authority'),
                        ('multi_location', 'Multi-Location Expansion'),
                        ('geo_citations', 'AI/GEO Citations'),
                        ('organic_growth', 'Overall Organic Growth'),
                    ],
                    default='local_leads',
                    max_length=50,
                )),
                ('priority_services', models.JSONField(default=list)),
                ('priority_locations', models.JSONField(default=list)),
                ('geo_priority_pages', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('site', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='goals',
                    to='sites.site',
                )),
            ],
            options={
                'db_table': 'site_goals',
            },
        ),
    ]
