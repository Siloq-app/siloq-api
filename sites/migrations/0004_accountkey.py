# Generated migration for AccountKey model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('sites', '0003_business_profile_onboarding'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Human-readable name for the API key', max_length=255)),
                ('key_hash', models.CharField(db_index=True, help_text='SHA-256 hash of the API key', max_length=64, unique=True)),
                ('key_prefix', models.CharField(help_text='First 16 characters of the key for display', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('usage_count', models.IntegerField(default=0)),
                ('sites_created', models.IntegerField(default=0, help_text='Number of sites auto-created with this key')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='account_keys', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'account_keys',
                'ordering': ['-created_at'],
            },
        ),
    ]
