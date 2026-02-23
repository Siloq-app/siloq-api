"""
Widen URL fields on seo_siteentityprofile from varchar(200) to text.
Google Maps URLs and social profile URLs regularly exceed 200 characters,
causing StringDataRightTruncation on profile.save() during GBP sync.

Model is managed=False so RunSQL is required.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0019_merge_20260221_1352'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE seo_siteentityprofile
                    ALTER COLUMN gbp_url TYPE text,
                    ALTER COLUMN url_facebook TYPE text,
                    ALTER COLUMN url_instagram TYPE text,
                    ALTER COLUMN url_linkedin TYPE text,
                    ALTER COLUMN url_twitter TYPE text,
                    ALTER COLUMN url_youtube TYPE text,
                    ALTER COLUMN url_tiktok TYPE text;
            """,
            reverse_sql="""
                ALTER TABLE seo_siteentityprofile
                    ALTER COLUMN gbp_url TYPE varchar(200),
                    ALTER COLUMN url_facebook TYPE varchar(200),
                    ALTER COLUMN url_instagram TYPE varchar(200),
                    ALTER COLUMN url_linkedin TYPE varchar(200),
                    ALTER COLUMN url_twitter TYPE varchar(200),
                    ALTER COLUMN url_youtube TYPE varchar(200),
                    ALTER COLUMN url_tiktok TYPE varchar(200);
            """,
        ),
    ]
