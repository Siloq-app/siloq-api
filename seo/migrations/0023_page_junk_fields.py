from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('seo', '0022_fix_json_to_jsonb_entity_profile')]
    operations = [
        migrations.AddField(
            model_name='page', name='junk_action',
            field=models.CharField(
                max_length=10, blank=True, null=True,
                choices=[('delete','Delete'),('noindex','Noindex'),('review','Needs Review')],
                help_text='Recommended action from junk detector',
            ),
        ),
        migrations.AddField(
            model_name='page', name='junk_reason',
            field=models.CharField(max_length=200, blank=True, null=True,
                help_text='Why this page was flagged as junk'),
        ),
    ]
