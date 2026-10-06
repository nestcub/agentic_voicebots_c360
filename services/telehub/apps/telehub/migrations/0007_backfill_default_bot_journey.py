from django.db import migrations


def backfill_default_journey(apps, schema_editor):
    """
    Wraps every pre-existing ProcessAgent's single graph in a BotJourney
    ("Sales Journey", order=0) so it fits the multi-journey model the same way
    a wizard-created agent now does: extracts the "Communication" node's
    config (the old home for bot_name/bot_id/dids/api_url/webhook_schema, see
    services/process_agent.py's pre-VoiceBot version) into a real VoiceBot row,
    then backfills bot_journey/current_bot_journey onto that agent's existing
    NodeInstance/Execution rows. Idempotent: skips any ProcessAgent that
    already has a BotJourney.
    """
    ProcessAgent = apps.get_model("telehub", "ProcessAgent")
    BotJourney = apps.get_model("telehub", "BotJourney")
    VoiceBot = apps.get_model("telehub", "VoiceBot")

    for agent in ProcessAgent.objects.all():
        if agent.bot_journeys.exists():
            continue

        communication_node = agent.nodes.filter(name="Communication").first()
        config = (communication_node.config if communication_node else {}) or {}

        voice_bot = VoiceBot.objects.create(
            process_agent=agent,
            label="Sales Bot",
            communication_type=config.get("communication_type", "") or "",
            bot_name=config.get("bot_name", "") or "",
            bot_id=config.get("bot_id", "") or "",
            dids=config.get("dids", []) or [],
            api_url=config.get("api_url", "") or "",
            webhook_schema=config.get("webhook_schema") or {},
        )
        bot_journey = BotJourney.objects.create(
            process_agent=agent, voice_bot=voice_bot, name="Sales Journey", order=0
        )

        agent.nodes.update(bot_journey=bot_journey)
        agent.executions.update(current_bot_journey=bot_journey)


def noop_reverse(apps, schema_editor):
    # Nothing to reverse to — the pre-migration state (voice data only in
    # NodeInstance.config) is untouched by the forward migration, it's only
    # ever added to, so there's nothing destructive to undo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("telehub", "0006_add_voicebot_botjourney"),
    ]

    operations = [
        migrations.RunPython(backfill_default_journey, noop_reverse),
    ]
