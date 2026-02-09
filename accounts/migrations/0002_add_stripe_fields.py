# Generated manually to add Stripe integration fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='stripe_customer_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='stripe_subscription_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='subscription_tier',
            field=models.CharField(blank=True, choices=[('pro', 'Pro'), ('builder', 'Builder+'), ('architect', 'Architect'), ('empire', 'Empire')], max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='subscription_status',
            field=models.CharField(choices=[('inactive', 'Inactive'), ('trial', 'Trial'), ('active', 'Active'), ('past_due', 'Past Due'), ('canceled', 'Canceled')], default='inactive', max_length=50),
        ),
        migrations.AddField(
            model_name='user',
            name='trial_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='trial_ends_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
