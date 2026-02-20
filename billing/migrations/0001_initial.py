# Generated manually for billing models

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_customer_id', models.CharField(blank=True, max_length=255)),
                ('stripe_subscription_id', models.CharField(blank=True, max_length=255)),
                ('tier', models.CharField(choices=[('free_trial', 'Free Trial'), ('pro', 'Pro'), ('builder_plus', 'Builder Plus'), ('architect', 'Architect'), ('empire', 'Empire')], default='free_trial', max_length=20)),
                ('status', models.CharField(choices=[('active', 'Active'), ('canceled', 'Canceled'), ('past_due', 'Past Due'), ('trialing', 'Trialing'), ('incomplete', 'Incomplete')], default='trialing', max_length=20)),
                ('trial_started_at', models.DateTimeField(blank=True, null=True)),
                ('trial_ends_at', models.DateTimeField(blank=True, null=True)),
                ('trial_pages_limit', models.IntegerField(default=10)),
                ('trial_pages_used', models.IntegerField(default=0)),
                ('current_period_start', models.DateTimeField(blank=True, null=True)),
                ('current_period_end', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='subscription', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'subscriptions',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_payment_intent_id', models.CharField(max_length=255)),
                ('stripe_invoice_id', models.CharField(blank=True, max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('currency', models.CharField(default='usd', max_length=3)),
                ('status', models.CharField(choices=[('succeeded', 'Succeeded'), ('failed', 'Failed'), ('pending', 'Pending'), ('refunded', 'Refunded')], max_length=20)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'payments',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Usage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('feature', models.CharField(choices=[('pages', 'Pages Analyzed'), ('scans', 'SEO Scans'), ('cannibalization', 'Cannibalization Analysis'), ('silo_analysis', 'Silo Analysis'), ('api_calls', 'API Calls')], max_length=30)),
                ('count', models.PositiveIntegerField(default=0)),
                ('period_start', models.DateTimeField()),
                ('period_end', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='usage_records', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'usage',
                'ordering': ['-created_at'],
                'unique_together': {('user', 'feature', 'period_start')},
            },
        ),
    ]
