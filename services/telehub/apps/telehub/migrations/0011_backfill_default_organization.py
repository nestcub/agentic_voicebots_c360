from django.conf import settings
from django.db import migrations

DEFAULT_ORG_SLUG = "excell-autovista"
DEFAULT_ORG_NAME = "Excell Autovista"
TENANT_MODELS = [
    "Department",
    "ProcessAgent",
    "VoiceBot",
    "Integration",
    "LeadSource",
    "WebhookDefinition",
    "Execution",
]


def backfill(apps, schema_editor):
    """Everything existing goes to Excell Autovista; `manage.py assign_org` moves Hyundai's rows out."""
    Organization = apps.get_model("telehub", "Organization")
    Membership = apps.get_model("telehub", "Membership")
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)

    org, _ = Organization.objects.get_or_create(
        slug=DEFAULT_ORG_SLUG, defaults={"name": DEFAULT_ORG_NAME}
    )
    for name in TENANT_MODELS:
        apps.get_model("telehub", name).objects.filter(organization__isnull=True).update(
            organization=org
        )
    for user in User.objects.all():
        Membership.objects.get_or_create(
            user=user, organization=org, defaults={"role": "admin"}
        )


class Migration(migrations.Migration):

    dependencies = [
        ("telehub", "0010_tenancy_models_nullable_org"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
