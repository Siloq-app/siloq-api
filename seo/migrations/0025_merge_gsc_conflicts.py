"""
Merge migration: brings 0006_conflicts_tab_models into the main migration chain.
It was orphaned (never merged), causing 'multiple leaf nodes' error.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0024_gsc_page_data'),
        ('seo', '0006_conflicts_tab_models'),
    ]

    operations = [
        # No schema changes — this is purely a merge to resolve the graph split.
    ]
