from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0005_page_post_type'),
        ('sites', '0005_site_gsc_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_id', models.CharField(db_index=True, max_length=36, unique=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='content_jobs', to='sites.site')),
                ('page_id', models.CharField(blank=True, max_length=255, null=True)),
                ('wp_post_id', models.IntegerField(blank=True, null=True)),
                ('job_type', models.CharField(default='content_generation', max_length=50)),
                ('status', models.CharField(
                    choices=[('pending', 'Pending'), ('processing', 'Processing'),
                             ('completed', 'Completed'), ('failed', 'Failed')],
                    default='pending', max_length=20)),
                ('result', models.JSONField(blank=True, null=True)),
                ('error', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'content_jobs', 'ordering': ['-created_at']},
        ),
    ]
