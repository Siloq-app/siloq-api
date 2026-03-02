# Add is_staff_exempt to Subscription; set True for user_id=19

from django.db import migrations, models


def set_staff_exempt_user_19(apps, schema_editor):
    Subscription = apps.get_model('billing', 'Subscription')
    Subscription.objects.filter(user_id=19).update(is_staff_exempt=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='is_staff_exempt',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(set_staff_exempt_user_19, noop),
    ]
