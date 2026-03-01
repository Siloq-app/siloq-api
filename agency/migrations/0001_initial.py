from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('sites', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AgencyProfile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('agency_name', models.CharField(max_length=255)),
                ('agency_slug', models.SlugField(max_length=100, unique=True)),
                ('white_label_tier', models.CharField(choices=[('PARTIAL', 'Agency - Powered by Siloq'), ('FULL', 'Agency Pro - Full Rebrand')], max_length=50)),
                ('max_client_seats', models.IntegerField(default=10)),
                ('logo_url', models.URLField(blank=True, max_length=2048)),
                ('logo_small_url', models.URLField(blank=True, max_length=2048)),
                ('favicon_url', models.URLField(blank=True, max_length=2048)),
                ('color_primary', models.CharField(default='#1A1A2E', max_length=7)),
                ('color_secondary', models.CharField(default='#E8D48B', max_length=7)),
                ('color_accent', models.CharField(default='#4ADE80', max_length=7)),
                ('color_background', models.CharField(default='#1A1A2E', max_length=7)),
                ('color_text', models.CharField(default='#F8F8F8', max_length=7)),
                ('support_email', models.EmailField(blank=True, max_length=254, null=True)),
                ('support_url', models.URLField(blank=True, null=True)),
                ('show_powered_by', models.BooleanField(default=True)),
                ('custom_domain', models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ('domain_verified', models.BooleanField(default=False)),
                ('domain_verified_at', models.DateTimeField(null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='agency_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'agency_profiles'},
        ),
        migrations.CreateModel(
            name='AgencyClientLink',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invite_email', models.EmailField(blank=True, max_length=254)),
                ('invite_token', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('invited_at', models.DateTimeField(auto_now_add=True)),
                ('accepted_at', models.DateTimeField(null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('agency', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='clients', to='agency.agencyprofile')),
                ('client_user', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='agency_link', to=settings.AUTH_USER_MODEL)),
                ('sites', models.ManyToManyField(blank=True, to='sites.site')),
            ],
            options={'db_table': 'agency_client_links'},
        ),
    ]
