from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0005_site_gsc_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='gbp_place_id',
            field=models.CharField(blank=True, help_text='Google Business Profile Place ID', max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_phone',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_address',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_website',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_url',
            field=models.URLField(blank=True, max_length=1000, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_reviews',
            field=models.JSONField(blank=True, default=list, help_text='Cached GBP reviews (4+ stars only)'),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_rating',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_review_count',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='site',
            name='gbp_last_synced_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
