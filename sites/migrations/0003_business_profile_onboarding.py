# Generated migration for business profile onboarding fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0002_site_sync_requested_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='site',
            name='business_type',
            field=models.CharField(
                blank=True,
                choices=[
                    ('local_service', 'Local/Service Business'),
                    ('ecommerce', 'E-Commerce'),
                    ('content_blog', 'Content/Blog'),
                    ('saas', 'SaaS/Software'),
                    ('other', 'Other'),
                ],
                help_text='Type of business',
                max_length=50,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='site',
            name='primary_services',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='List of main services/products the business offers',
            ),
        ),
        migrations.AddField(
            model_name='site',
            name='service_areas',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='List of geographic areas served (for local businesses)',
            ),
        ),
        migrations.AddField(
            model_name='site',
            name='target_audience',
            field=models.TextField(
                blank=True,
                help_text='Description of target audience/customers',
            ),
        ),
        migrations.AddField(
            model_name='site',
            name='business_description',
            field=models.TextField(
                blank=True,
                help_text='Brief description of the business',
            ),
        ),
        migrations.AddField(
            model_name='site',
            name='onboarding_complete',
            field=models.BooleanField(
                default=False,
                help_text='Whether the business onboarding wizard has been completed',
            ),
        ),
    ]
