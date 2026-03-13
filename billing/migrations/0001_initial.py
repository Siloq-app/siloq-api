"""
Initial migration for billing app.
Creates all billing models: Subscription, Payment, Usage, SiteCredits, CreditTransaction.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sites", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stripe_customer_id", models.CharField(blank=True, max_length=255)),
                ("stripe_subscription_id", models.CharField(blank=True, max_length=255)),
                ("tier", models.CharField(choices=[("free_trial", "Free Trial"), ("pro", "Pro"), ("builder_plus", "Builder Plus"), ("architect", "Architect"), ("empire", "Empire")], default="free_trial", max_length=20)),
                ("status", models.CharField(choices=[("active", "Active"), ("canceled", "Canceled"), ("past_due", "Past Due"), ("trialing", "Trialing"), ("incomplete", "Incomplete")], default="trialing", max_length=20)),
                ("trial_started_at", models.DateTimeField(blank=True, null=True)),
                ("trial_ends_at", models.DateTimeField(blank=True, null=True)),
                ("trial_pages_limit", models.IntegerField(default=10)),
                ("trial_pages_used", models.IntegerField(default=0)),
                ("current_period_start", models.DateTimeField(blank=True, null=True)),
                ("current_period_end", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="subscription", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "subscriptions",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stripe_payment_intent_id", models.CharField(max_length=255)),
                ("stripe_invoice_id", models.CharField(blank=True, max_length=255)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("currency", models.CharField(default="usd", max_length=3)),
                ("status", models.CharField(choices=[("succeeded", "Succeeded"), ("failed", "Failed"), ("pending", "Pending"), ("refunded", "Refunded")], max_length=20)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "payments",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Usage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("feature", models.CharField(choices=[("pages", "Pages Analyzed"), ("scans", "SEO Scans"), ("cannibalization", "Cannibalization Analysis"), ("silo_analysis", "Silo Analysis"), ("api_calls", "API Calls")], max_length=30)),
                ("count", models.PositiveIntegerField(default=0)),
                ("period_start", models.DateTimeField()),
                ("period_end", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="usage_records", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "usage",
                "ordering": ["-created_at"],
                "unique_together": {("user", "feature", "period_start")},
            },
        ),
        migrations.CreateModel(
            name="SiteCredits",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan_tier", models.CharField(default="free_trial", max_length=20)),
                ("monthly_allowance", models.IntegerField(default=0)),
                ("current_balance", models.IntegerField(default=0)),
                ("lifetime_used", models.IntegerField(default=0)),
                ("reset_date", models.DateField(blank=True, null=True)),
                ("is_trial", models.BooleanField(default=True)),
                ("trial_actions_remaining", models.IntegerField(default=25)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("site", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="credits", to="sites.site")),
            ],
            options={
                "db_table": "billing_site_credits",
                "verbose_name": "Site Credits",
                "verbose_name_plural": "Site Credits",
            },
        ),
        migrations.CreateModel(
            name="CreditTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action_type", models.CharField(choices=[("auto_add_link", "Auto-Add Internal Link"), ("schema_generation", "Schema Generation"), ("content_draft", "Content Draft"), ("widget_intelligence", "Widget Intelligence"), ("bulk_operation", "Bulk Site Operation"), ("content_engine", "Content Engine Run"), ("site_audit", "Site Audit"), ("cannibalization_analysis", "Cannibalization Analysis"), ("manual_adjustment", "Manual Adjustment"), ("purchase", "Credit Purchase")], default="manual_adjustment", max_length=50)),
                ("cost", models.IntegerField(default=1)),
                ("note", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("site_credits", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transactions", to="billing.sitecredits")),
            ],
            options={
                "db_table": "billing_credit_transactions",
                "ordering": ["-created_at"],
            },
        ),
    ]
