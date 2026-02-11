# Generated migration for is_money_page field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='is_money_page',
            field=models.BooleanField(default=False, help_text='Is this a money/target page?'),
        ),
    ]
