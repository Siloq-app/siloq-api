# Generated manually for internal links feature

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0001_initial'),
        ('seo', '0003_page_is_noindex'),
    ]

    operations = [
        # Add is_homepage field to Page
        migrations.AddField(
            model_name='page',
            name='is_homepage',
            field=models.BooleanField(default=False, help_text='Is this the homepage?'),
        ),
        
        # Add parent_silo field to Page (self-referencing FK)
        migrations.AddField(
            model_name='page',
            name='parent_silo',
            field=models.ForeignKey(
                blank=True,
                help_text='The money page this supporting page belongs to',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='supporting_pages',
                to='seo.page',
            ),
        ),
        
        # Create InternalLink model
        migrations.CreateModel(
            name='InternalLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_url', models.URLField(help_text='The URL being linked to')),
                ('anchor_text', models.CharField(blank=True, help_text='The clickable text of the link', max_length=500)),
                ('anchor_text_normalized', models.CharField(blank=True, help_text='Lowercase, stripped anchor text for comparison', max_length=500)),
                ('context_text', models.TextField(blank=True, help_text='Surrounding text for context (±50 chars)')),
                ('is_in_content', models.BooleanField(default=True, help_text='Is this link in main content (vs nav/footer)?')),
                ('is_nofollow', models.BooleanField(default=False, help_text='Does this link have rel=nofollow?')),
                ('is_valid', models.BooleanField(default=True, help_text='Is this a valid internal link?')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='internal_links', to='sites.site')),
                ('source_page', models.ForeignKey(help_text='The page containing the link', on_delete=django.db.models.deletion.CASCADE, related_name='outgoing_links', to='seo.page')),
                ('target_page', models.ForeignKey(blank=True, help_text='The page being linked to (null if external or not found)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='incoming_links', to='seo.page')),
            ],
            options={
                'db_table': 'internal_links',
                'ordering': ['-created_at'],
            },
        ),
        
        # Create AnchorTextConflict model
        migrations.CreateModel(
            name='AnchorTextConflict',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anchor_text', models.CharField(help_text='The conflicting anchor text', max_length=500)),
                ('anchor_text_normalized', models.CharField(help_text='Lowercase normalized anchor', max_length=500)),
                ('occurrence_count', models.IntegerField(default=0, help_text='How many times this anchor appears across the site')),
                ('severity', models.CharField(choices=[('high', 'High'), ('medium', 'Medium'), ('low', 'Low')], default='medium', max_length=20)),
                ('is_resolved', models.BooleanField(default=False)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='anchor_conflicts', to='sites.site')),
                ('conflicting_pages', models.ManyToManyField(help_text='Pages this anchor text links to', related_name='anchor_conflicts', to='seo.page')),
            ],
            options={
                'db_table': 'anchor_text_conflicts',
                'ordering': ['-severity', '-occurrence_count'],
            },
        ),
        
        # Create LinkIssue model
        migrations.CreateModel(
            name='LinkIssue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('issue_type', models.CharField(choices=[
                    ('anchor_conflict', 'Anchor Text Conflict'),
                    ('homepage_theft', 'Homepage Anchor Theft'),
                    ('missing_target_link', 'Missing Link to Target'),
                    ('missing_sibling_links', 'Missing Sibling Links'),
                    ('orphan_page', 'Orphan Page'),
                    ('cross_silo_link', 'Cross-Silo Link'),
                    ('too_many_supporting', 'Too Many Supporting Pages'),
                ], max_length=50)),
                ('severity', models.CharField(choices=[('high', 'High'), ('medium', 'Medium'), ('low', 'Low')], default='medium', max_length=20)),
                ('description', models.TextField()),
                ('recommendation', models.TextField(blank=True)),
                ('anchor_text', models.CharField(blank=True, max_length=500)),
                ('is_resolved', models.BooleanField(default=False)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='link_issues', to='sites.site')),
                ('page', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='link_issues', to='seo.page')),
                ('related_pages', models.ManyToManyField(blank=True, related_name='related_link_issues', to='seo.page')),
            ],
            options={
                'db_table': 'link_issues',
                'ordering': ['-severity', '-created_at'],
            },
        ),
        
        # Add indexes
        migrations.AddIndex(
            model_name='page',
            index=models.Index(fields=['is_money_page'], name='pages_is_mone_idx'),
        ),
        migrations.AddIndex(
            model_name='page',
            index=models.Index(fields=['is_homepage'], name='pages_is_home_idx'),
        ),
        migrations.AddIndex(
            model_name='internallink',
            index=models.Index(fields=['site', 'source_page'], name='internal_links_site_source_idx'),
        ),
        migrations.AddIndex(
            model_name='internallink',
            index=models.Index(fields=['site', 'target_page'], name='internal_links_site_target_idx'),
        ),
        migrations.AddIndex(
            model_name='internallink',
            index=models.Index(fields=['anchor_text_normalized'], name='internal_links_anchor_idx'),
        ),
    ]
