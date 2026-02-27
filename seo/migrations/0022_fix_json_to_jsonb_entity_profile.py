"""
Fix: Change brands_used and team_members columns from JSON to JSONB.

Migration 0021 created these columns as JSON type. Django 5 + psycopg2 2.9
only registers custom decode adapters for JSONB (OID 3802), not plain JSON
(OID 114). psycopg2 auto-decodes JSON columns to Python objects, then
Django's JSONField.from_db_value calls json.loads() on the already-decoded
object → TypeError: the JSON object must be str, bytes or bytearray, not list.

Changing to JSONB aligns with all other JSONField columns in the model
(categories, service_cities, hours, gbp_reviews, etc.).
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0021_page_builder_field_entity_profile_v1_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE seo_siteentityprofile
                    ALTER COLUMN brands_used  TYPE jsonb USING brands_used::jsonb,
                    ALTER COLUMN team_members TYPE jsonb USING team_members::jsonb;
            """,
            reverse_sql="""
                ALTER TABLE seo_siteentityprofile
                    ALTER COLUMN brands_used  TYPE json USING brands_used::json,
                    ALTER COLUMN team_members TYPE json USING team_members::json;
            """,
        ),
    ]
