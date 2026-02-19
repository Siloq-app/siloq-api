from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('seo', '0016_pageclassification_entities'),
    ]
    operations = [
        migrations.AddField(
            model_name='pageanalysis',
            name='generated_schema',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
