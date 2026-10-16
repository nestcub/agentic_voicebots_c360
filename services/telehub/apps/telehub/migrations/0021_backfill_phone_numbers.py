from django.db import migrations

from apps.telehub.services.phone import normalize_digits


def backfill_phone_numbers(apps, schema_editor):
    """
    One PhoneNumber per entry of every VoiceBot.dids list. The same number may
    be on several bots, so uniqueness is only checked within a bot (two
    spellings of one number on the same bot collapse to one row).
    """
    VoiceBot = apps.get_model("telehub", "VoiceBot")
    PhoneNumber = apps.get_model("telehub", "PhoneNumber")

    for bot in VoiceBot.objects.order_by("id"):
        taken = set(PhoneNumber.objects.filter(voice_bot=bot).values_list("did_key", flat=True))
        for did in bot.dids or []:
            did = str(did).strip()
            key = normalize_digits(did)
            if not key or key in taken:
                continue
            taken.add(key)
            PhoneNumber.objects.create(
                organization_id=bot.organization_id, voice_bot=bot, did=did[:32], did_key=key[:32]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("telehub", "0020_phone_numbers_transitions_parent_execution"),
    ]

    operations = [
        migrations.RunPython(backfill_phone_numbers, migrations.RunPython.noop),
    ]
