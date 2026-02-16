"""
Add page_type_classification and page_type_override fields to Page model.
Backfill from is_money_page and post_type.

MUST be idempotent — safe to run multiple times.
"""
from django.db import migrations, models


def backfill_page_types(apps, schema_editor):
    """Backfill page_type_classification from existing fields."""
    from django.db import connection
    cursor = connection.cursor()

    # Check if column exists before backfilling
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='pages' AND column_name='page_type_classification'"
    )
    if not cursor.fetchone():
        return  # Column doesn't exist yet, skip

    # Set money pages
    cursor.execute(
        "UPDATE pages SET page_type_classification='money' "
        "WHERE is_money_page=true AND page_type_classification='supporting'"
    )
    # Set product pages
    cursor.execute(
        "UPDATE pages SET page_type_classification='product' "
        "WHERE post_type='product' AND page_type_classification='supporting' "
        "AND is_money_page=false"
    )


def reverse_backfill(apps, schema_editor):
    pass  # No-op reverse


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0008_alter_anchortextconflict_anchor_text_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='page',
            name='page_type_classification',
            field=models.CharField(
                max_length=20,
                default='supporting',
                choices=[
                    ('money', 'Money Page'),
                    ('supporting', 'Supporting Content'),
                    ('utility', 'Utility Page'),
                    ('conversion', 'Conversion Page'),
                    ('archive', 'Archive / Index'),
                    ('product', 'E-commerce Product'),
                ],
                help_text='6-type page classification',
            ),
        ),
        migrations.AddField(
            model_name='page',
            name='page_type_override',
            field=models.BooleanField(
                default=False,
                help_text='True if user manually set the page type (skip auto-reclassification)',
            ),
        ),
        migrations.AddIndex(
            model_name='page',
            index=models.Index(fields=['page_type_classification'], name='pages_page_ty_classif_idx'),
        ),
        migrations.RunPython(backfill_page_types, reverse_backfill),
    ]
