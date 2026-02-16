"""Add page_type_classification and page_type_override to pages table."""
from django.db import migrations, models


def add_classification_columns(apps, schema_editor):
    """Idempotent: add columns if they don't exist."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'pages' AND column_name IN ('page_type_classification', 'page_type_override')
        """)
        existing = {row[0] for row in cursor.fetchall()}

        if 'page_type_classification' not in existing:
            cursor.execute("""
                ALTER TABLE pages
                ADD COLUMN page_type_classification varchar(20) NOT NULL DEFAULT 'supporting'
            """)

        if 'page_type_override' not in existing:
            cursor.execute("""
                ALTER TABLE pages
                ADD COLUMN page_type_override boolean NOT NULL DEFAULT false
            """)

        # Reset all is_money_page to false — classifier will set correctly
        cursor.execute("UPDATE pages SET is_money_page = false")

        # Backfill products
        cursor.execute("""
            UPDATE pages SET page_type_classification = 'product'
            WHERE post_type = 'product'
        """)

        # Add index if not exists
        cursor.execute("""
            SELECT 1 FROM pg_indexes WHERE tablename = 'pages' AND indexname = 'pages_classified_type_idx'
        """)
        if not cursor.fetchone():
            cursor.execute("""
                CREATE INDEX pages_classified_type_idx ON pages (site_id, page_type_classification)
            """)


class Migration(migrations.Migration):
    dependencies = [
        ('seo', '0008_alter_anchortextconflict_anchor_text_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_classification_columns, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='page',
                    name='page_type_classification',
                    field=models.CharField(
                        max_length=20, default='supporting',
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
            ],
        ),
    ]
