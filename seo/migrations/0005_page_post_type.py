# Generated manually for post_type field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0004_internal_links'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='post_type',
            field=models.CharField(
                default='page',
                help_text='WordPress post type: page, post, product, product_cat',
                max_length=50,
            ),
        ),
    ]
