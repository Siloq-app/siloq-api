from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0026_site_intelligence'),
        ('seo', '0026_siteaudit'),
    ]

    operations = [
        migrations.AddField(
            model_name='siteentityprofile',
            name='brand_voice',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
