# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='sync_requested_at',
            field=models.DateTimeField(blank=True, null=True, help_text='When user requested a sync from dashboard'),
        ),
    ]
