"""
Add blog_overlap_count to AnalysisRun.
Tracks the number of BLOG_OVERLAP conflicts (blog vs service page) found per run.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seo', '0011_merge_0010_flip_flop_0010_thin_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisrun',
            name='blog_overlap_count',
            field=models.IntegerField(
                default=0,
                help_text='BLOG_OVERLAP bucket count (blog vs service page conflicts)',
            ),
        ),
    ]
