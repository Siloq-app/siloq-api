"""
Add thin content fields to PageClassification model.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0009_page_classification'),
    ]

    operations = [
        migrations.AddField(
            model_name='pageclassification',
            name='word_count',
            field=models.IntegerField(default=0, help_text='Word count from SEOData'),
        ),
        migrations.AddField(
            model_name='pageclassification',
            name='is_thin_content',
            field=models.BooleanField(default=False, help_text='True if word_count < 300'),
        ),
        migrations.AddField(
            model_name='pageclassification',
            name='is_critically_thin',
            field=models.BooleanField(default=False, help_text='True if word_count < 100'),
        ),
    ]
