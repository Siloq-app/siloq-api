# Generated manually for GSC integration fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0004_accountkey'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='gsc_site_url',
            field=models.URLField(blank=True, null=True, help_text='GSC property URL (e.g., https://example.com/)'),
        ),
        migrations.AddField(
            model_name='site',
            name='gsc_access_token',
            field=models.TextField(blank=True, null=True, help_text='GSC OAuth access token'),
        ),
        migrations.AddField(
            model_name='site',
            name='gsc_refresh_token',
            field=models.TextField(blank=True, null=True, help_text='GSC OAuth refresh token'),
        ),
        migrations.AddField(
            model_name='site',
            name='gsc_token_expires_at',
            field=models.DateTimeField(blank=True, null=True, help_text='When the access token expires'),
        ),
        migrations.AddField(
            model_name='site',
            name='gsc_connected_at',
            field=models.DateTimeField(blank=True, null=True, help_text='When GSC was connected'),
        ),
    ]
