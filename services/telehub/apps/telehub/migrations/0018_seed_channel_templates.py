from django.db import migrations

from apps.telehub.services import omnichannel_seed


def seed_channel_templates(apps, schema_editor):
    """
    Every agent with an OmnichannelConfig gets its T1/T2/T3 curls as
    ChannelTemplate rows plus the default rules that reproduce the old
    hardcoded Hyundai selection (see services/omnichannel_seed.py). Uses the
    same pure function as runtime so the two cannot drift.
    """
    OmnichannelConfig = apps.get_model("telehub", "OmnichannelConfig")
    ChannelTemplate = apps.get_model("telehub", "ChannelTemplate")
    ChannelRule = apps.get_model("telehub", "ChannelRule")

    for config in OmnichannelConfig.objects.select_related("process_agent"):
        curls = omnichannel_seed.legacy_curls(config)
        if any(curl.strip() for curl in curls.values()):
            omnichannel_seed.sync_agent(ChannelTemplate, ChannelRule, config.process_agent, curls)


class Migration(migrations.Migration):

    dependencies = [
        ("telehub", "0017_channel_templates_and_rules"),
    ]

    operations = [
        migrations.RunPython(seed_channel_templates, migrations.RunPython.noop),
    ]
