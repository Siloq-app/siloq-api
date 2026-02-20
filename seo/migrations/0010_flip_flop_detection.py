# Generated migration for flip-flop detection

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0009_page_classification'),
    ]

    operations = [
        migrations.AddField(
            model_name='cannibalizationconflict',
            name='flip_flop_detected',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='cannibalizationconflict',
            name='flip_flop_correlation',
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=4, null=True),
        ),
        migrations.AddField(
            model_name='cannibalizationconflict',
            name='position_volatility',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='cannibalizationconflict',
            name='metadata',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
