"""
Add page_builder field to Page model.
Add logo_url, brands_used, url_yelp, team_members, is_service_area_business to SiteEntityProfile.

SiteEntityProfile is managed=False so we use RunSQL for the DB columns.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0020_widen_entity_profile_url_fields'),
    ]

    operations = [
        # ── Page.page_builder (managed=True, normal AddField) ─────────────────
        migrations.AddField(
            model_name='page',
            name='page_builder',
            field=models.CharField(
                max_length=30,
                default='unknown',
                blank=True,
                choices=[
                    ('standard',       'Standard WordPress'),
                    ('gutenberg',      'Gutenberg Block Editor'),
                    ('elementor',      'Elementor'),
                    ('cornerstone',    'Cornerstone / X Theme'),
                    ('divi',           'Divi'),
                    ('wpbakery',       'WPBakery'),
                    ('beaver_builder', 'Beaver Builder'),
                    ('unknown',        'Unknown'),
                ],
                help_text='Page builder detected during sync',
            ),
        ),

        # ── SiteEntityProfile new columns (managed=False → RunSQL) ───────────
        migrations.RunSQL(
            sql="""
                ALTER TABLE seo_siteentityprofile
                    ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500) NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS brands_used JSON NOT NULL DEFAULT '[]',
                    ADD COLUMN IF NOT EXISTS url_yelp VARCHAR(500) NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS team_members JSON NOT NULL DEFAULT '[]',
                    ADD COLUMN IF NOT EXISTS is_service_area_business BOOLEAN NOT NULL DEFAULT FALSE;
            """,
            reverse_sql="""
                ALTER TABLE seo_siteentityprofile
                    DROP COLUMN IF EXISTS logo_url,
                    DROP COLUMN IF EXISTS brands_used,
                    DROP COLUMN IF EXISTS url_yelp,
                    DROP COLUMN IF EXISTS team_members,
                    DROP COLUMN IF EXISTS is_service_area_business;
            """,
        ),
    ]
