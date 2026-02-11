# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0002_page_is_money_page'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='is_noindex',
            field=models.BooleanField(default=False, help_text='Is this page set to noindex?'),
        ),
    ]
