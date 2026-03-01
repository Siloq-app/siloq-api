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
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('agency_name',       models.CharField(max_length=255)),
                ('agency_slug',       models.SlugField(unique=True)),
                ('white_label_tier',  models.CharField(max_length=50, choices=[('PARTIAL','Agency - Powered by Siloq'),('FULL','Agency Pro - Full Rebrand')])),
                ('max_sites',         models.IntegerField(default=10)),
                ('logo_url',          models.URLField(blank=True, null=True, max_length=2048)),
                ('logo_small_url',    models.URLField(blank=True, null=True, max_length=2048)),
                ('favicon_url',       models.URLField(blank=True, null=True, max_length=2048)),
                ('color_primary',     models.CharField(max_length=7, default='#1A1A2E')),
                ('color_secondary',   models.CharField(max_length=7, default='#E8D48B')),
                ('color_accent',      models.CharField(max_length=7, default='#4ADE80')),
                ('support_email',     models.EmailField(blank=True, null=True)),
                ('support_url',       models.URLField(blank=True, null=True)),
                ('custom_domain',     models.CharField(max_length=255, blank=True, null=True, unique=True)),
                ('domain_verified',   models.BooleanField(default=False)),
                ('domain_verified_at',models.DateTimeField(null=True, blank=True)),
                ('created_at',        models.DateTimeField(auto_now_add=True)),
                ('updated_at',        models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='agency_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'agency_profiles'},
        ),
        migrations.CreateModel(
            name='AgencyClientSite',
            fields=[
                ('id',        models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ('added_at',  models.DateTimeField(auto_now_add=True)),
                ('is_active', models.BooleanField(default=True)),
                ('agency',       models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='client_sites', to='agency.agencyprofile')),
                ('site',         models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='agency_link', to='sites.site')),
                ('client_user',  models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='agency_sites', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'agency_client_sites'},
        ),
        migrations.AddConstraint(
            model_name='agencyclientsite',
            constraint=models.UniqueConstraint(fields=['agency', 'site'], name='unique_agency_site'),
        ),
    ]
