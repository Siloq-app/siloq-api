import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('sites', '0001_initial'),
        ('seo', '0025_merge_gsc_conflicts'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteAudit',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(default='complete', max_length=20)),
                ('site_score', models.IntegerField(default=0)),
                ('site_context', models.JSONField(default=dict)),
                ('results', models.JSONField(default=list)),
                ('ai_provider', models.CharField(blank=True, max_length=30)),
                ('ai_model', models.CharField(blank=True, max_length=60)),
                ('pages_audited', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audits', to='sites.site')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audits', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'site_audits',
                'ordering': ['-created_at'],
            },
        ),
    ]
