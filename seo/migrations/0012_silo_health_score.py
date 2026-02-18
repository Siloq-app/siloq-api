"""
Migration: Add SiloHealthScore model for tracking silo health over time.
"""
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0011_pageclassification_thin_content'),
        ('sites', '0005_site_gsc_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiloHealthScore',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4,
                    editable=False,
                    primary_key=True,
                    serialize=False,
                )),
                ('score', models.DecimalField(decimal_places=2, max_digits=5)),
                ('component_scores', models.JSONField(default=dict)),
                ('page_count', models.IntegerField(default=0)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('trigger', models.CharField(
                    choices=[
                        ('gsc_connect', 'GSC Connection'),
                        ('conflict_resolution', 'Conflict Resolution'),
                        ('on_demand', 'On-Demand'),
                        ('scheduled', 'Scheduled'),
                    ],
                    default='on_demand',
                    max_length=30,
                )),
                ('calculated_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('site', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='silo_health_scores',
                    to='sites.site',
                )),
                ('silo', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='health_scores',
                    to='seo.silodefinition',
                )),
            ],
            options={
                'db_table': 'silo_health_scores',
                'ordering': ['-calculated_at'],
            },
        ),
        migrations.AddIndex(
            model_name='silohealthscore',
            index=models.Index(fields=['site'], name='silo_health_site_idx'),
        ),
        migrations.AddIndex(
            model_name='silohealthscore',
            index=models.Index(fields=['silo'], name='silo_health_silo_idx'),
        ),
        migrations.AddIndex(
            model_name='silohealthscore',
            index=models.Index(fields=['site', 'calculated_at'], name='silo_health_site_calc_idx'),
        ),
        migrations.AddIndex(
            model_name='silohealthscore',
            index=models.Index(fields=['silo', 'calculated_at'], name='silo_health_silo_calc_idx'),
        ),
    ]
