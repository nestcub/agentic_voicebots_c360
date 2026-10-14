from django.db import migrations, models


class Migration(migrations.Migration):
    """Run `manage.py check_tenancy` first: duplicate secrets must be regenerated or this fails."""

    dependencies = [
        ("telehub", "0012_org_not_null"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="webhookdefinition",
            constraint=models.UniqueConstraint(
                condition=models.Q(("secret", ""), _negated=True),
                fields=("secret",),
                name="unique_webhook_secret",
            ),
        ),
    ]
