import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Every tenant row now has an org (0011 backfilled; all write paths set it)."""

    dependencies = [
        ("telehub", "0011_backfill_default_organization"),
    ]

    operations = [
        migrations.AlterField(
            model_name="department",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="departments",
                to="telehub.organization",
            ),
        ),
        migrations.AlterField(
            model_name="execution",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="executions",
                to="telehub.organization",
            ),
        ),
        migrations.AlterField(
            model_name="integration",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="integrations",
                to="telehub.organization",
            ),
        ),
        migrations.AlterField(
            model_name="leadsource",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lead_sources",
                to="telehub.organization",
            ),
        ),
        migrations.AlterField(
            model_name="processagent",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="process_agents",
                to="telehub.organization",
            ),
        ),
        migrations.AlterField(
            model_name="voicebot",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="voice_bots",
                to="telehub.organization",
            ),
        ),
        migrations.AlterField(
            model_name="webhookdefinition",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="webhooks",
                to="telehub.organization",
            ),
        ),
    ]
