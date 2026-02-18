"""
Merge migration: resolves the two parallel 0010_* migrations.
- 0010_flip_flop_detection (adds flip-flop fields to CannibalizationConflict)
- 0010_pageclassification_thin_content (adds thin content fields to PageClassification)
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0010_flip_flop_detection'),
        ('seo', '0010_pageclassification_thin_content'),
    ]

    operations = [
    ]
