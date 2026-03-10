"""Add gsc_available_properties and gsc_auto_matched fields to Site."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0006_site_gbp_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='gsc_available_properties',
            field=models.TextField(blank=True, null=True, help_text='JSON list of all GSC properties available on the user\'s Google account'),
        ),
        migrations.AddField(
            model_name='site',
            name='gsc_auto_matched',
            field=models.BooleanField(default=False, help_text='True if gsc_site_url was auto-matched by domain'),
        ),
    ]
