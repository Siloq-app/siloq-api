from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AgencyProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('agency_name', models.CharField(max_length=255)),
                ('agency_slug', models.SlugField(max_length=100, unique=True)),
                ('white_label_tier', models.CharField(
                    choices=[
                        ('NO_WHITE_LABEL', 'No White Label'),
                        ('PARTIAL_WHITE_LABEL', 'Partial (Agency)'),
                        ('FULL_WHITE_LABEL', 'Full (Empire)'),
                    ],
                    default='NO_WHITE_LABEL',
                    max_length=50,
                )),
                ('logo_url', models.URLField(blank=True, max_length=2048)),
                ('logo_small_url', models.URLField(blank=True, max_length=2048)),
                ('favicon_url', models.URLField(blank=True, max_length=2048)),
                ('color_primary', models.CharField(default='#E8D48B', max_length=7)),
                ('color_secondary', models.CharField(default='#C8A951', max_length=7)),
                ('color_accent', models.CharField(default='#3B82F6', max_length=7)),
                ('color_background', models.CharField(default='#1A1A2E', max_length=7)),
                ('color_text', models.CharField(default='#F8F8F8', max_length=7)),
                ('support_email', models.EmailField(blank=True, max_length=254)),
                ('support_url', models.URLField(blank=True)),
                ('tagline', models.CharField(blank=True, max_length=255)),
                ('custom_domain', models.CharField(blank=True, max_length=255)),
                ('domain_verified', models.BooleanField(default=False)),
                ('domain_verified_at', models.DateTimeField(blank=True, null=True)),
                ('show_powered_by', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='agency_profile',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'db_table': 'agency_profiles',
            },
        ),
        migrations.CreateModel(
            name='AgencyClientLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('active', 'Active'),
                        ('invited', 'Invited'),
                        ('suspended', 'Suspended'),
                    ],
                    default='active',
                    max_length=20,
                )),
                ('invite_email', models.EmailField(blank=True, max_length=254)),
                ('invite_token', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('invited_at', models.DateTimeField(auto_now_add=True)),
                ('accepted_at', models.DateTimeField(blank=True, null=True)),
                ('agency', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='agency_clients',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('client', models.ForeignKey(
                    null=True,
                    blank=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='agency_memberships',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'db_table': 'agency_client_links',
            },
        ),
        migrations.AlterUniqueTogether(
            name='agencyclientlink',
            unique_together={('agency', 'client')},
        ),
    ]
