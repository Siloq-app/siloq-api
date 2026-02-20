from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0005_page_post_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='page_type_classification',
            field=models.CharField(
                max_length=50, blank=True, null=True,
                help_text='Auto-classified page type: money, supporting, utility, conversion, archive, product'
            ),
        ),
        migrations.AddField(
            model_name='page',
            name='page_type_override',
            field=models.CharField(
                max_length=50, blank=True, null=True,
                help_text='Manual override for page type classification'
            ),
        ),
    ]
