"""
Add entities JSONField to PageClassification model.

Phase 0.5 — Entity Extraction stores named entities (brand, brand_line,
product_name, product_category, service_type, location, descriptor,
sport_filter) extracted by Claude in batch, once per site, before any
overlap comparisons run.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0015_slug_change_log'),
    ]

    operations = [
        migrations.AddField(
            model_name='pageclassification',
            name='entities',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text=(
                    'Named entities extracted by Phase 0.5: '
                    '[{"text": "Chasse Performance", "type": "brand_line", "confidence": 0.95}, ...]'
                ),
            ),
        ),
    ]
