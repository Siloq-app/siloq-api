from django.db import migrations, models


def add_page_type_columns_safe(apps, schema_editor):
    """Add page_type_classification and page_type_override columns if they don't already exist."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE pages ADD COLUMN IF NOT EXISTS page_type_classification VARCHAR(50) NULL"
        )
        cursor.execute(
            "ALTER TABLE pages ADD COLUMN IF NOT EXISTS page_type_override VARCHAR(50) NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0005_page_post_type'),
    ]

    operations = [
        # RunPython uses IF NOT EXISTS — safe to re-run on a DB that already has these columns
        migrations.RunPython(
            add_page_type_columns_safe,
            reverse_code=migrations.RunPython.noop,
        ),
        # SeparateDatabaseAndState: update Django's migration state without touching the DB
        # (the DB work was done above by RunPython)
        migrations.SeparateDatabaseAndState(
            state_operations=[
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
            ],
            database_operations=[],
        ),
    ]
