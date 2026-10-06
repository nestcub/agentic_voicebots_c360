from django.utils import timezone

from ..models import Execution, LeadSource

NODE_NAME_LEAD_RECEIVED = "Lead Received"


def launch_campaign(process_agent, payload: dict) -> dict:
    """
    payload: {"campaign_id": str, "leads"?: [{"to_number": str, "params": dict, "dnd"?: str, "lead_id"?: str}],
    "bot_journey_id"?: int}

    "bot_journey_id" pins every created Execution's current_bot_journey to a
    specific BotJourney (e.g. dispatching a manual test call through a
    non-default VoiceBot); omitted or unrecognized falls back to the process
    agent's first journey by order.

    Bulk-creates one Execution per lead: status="pending", current_node="Lead Received",
    campaign_id=payload["campaign_id"], variables = params merged with {"to_number": to_number}
    and {"dnd": dnd} if the lead dict has a "dnd" key. lead_id = lead.get("lead_id") or
    f"{campaign_id}-{index}". next_execution=now() so run_scheduler's tick() (which polls
    next_execution__lte=now()) picks these up immediately — a NULL next_execution never
    matches that filter, so leaving it unset would make launched leads invisible to the
    scheduler forever. Rows missing to_number are skipped (not created), their lead_id
    (or "row-{index}" if absent) collected into the returned skipped list — never silently
    dropped without being accounted for. Uses Execution.objects.bulk_create for the actual
    insert. Returns {"campaign_id": str, "created_count": int, "skipped": list[str]}.

    Lead sourcing: if the caller supplies "leads" explicitly, those are used as given and
    also persisted onto the ProcessAgent's LeadSource (most recently created row, or a new
    "upload" one if none exists yet) so this becomes replayable later without re-uploading —
    this is the "lead source entered during agent creation, updatable after" contract. If
    "leads" is omitted/empty, leads are instead read from that same stored LeadSource:
    `configuration["leads"]` for most types, or a single `{"to_number": configuration["number"]}`
    lead for type="single_source". So a campaign can be relaunched against whatever the source
    currently holds (edited via the LeadSource GET/PATCH endpoint, a previous upload, or the
    wizard's single-source number). The dashboard only exposes a no-payload relaunch button for
    single_source + voice_outbound processes (this POC's scope) — this function itself has no
    such restriction, it just reflects whatever LeadSource is stored.
    """
    campaign_id = payload.get("campaign_id", "")
    leads = payload.get("leads", []) or []

    if leads:
        lead_source = process_agent.lead_sources.order_by("-created_at").first()
        if lead_source is None:
            lead_source = LeadSource(process_agent=process_agent, type="upload")
        lead_source.configuration = {**lead_source.configuration, "leads": leads}
        if "field_mapping" in payload:
            lead_source.field_mapping = payload["field_mapping"]
        lead_source.save()
    else:
        lead_source = process_agent.lead_sources.order_by("-created_at").first()
        if lead_source is not None:
            if lead_source.type == "single_source":
                number = lead_source.configuration.get("number")
                if number:
                    leads = [{"to_number": number, "lead_id": "single-source"}]
            else:
                leads = lead_source.configuration.get("leads", []) or []

    executions = []
    skipped = []

    # Every new Execution starts in a BotJourney so node-name lookups (Retry,
    # Callback, Communication, ...) resolve unambiguously once a second journey
    # exists. Defaults to the process agent's first journey (by order) — e.g.
    # "Sales Journey" — but a caller with a specific bot in mind (the Runs tab
    # or QA tab's follow-up dispatch, once multiple VoiceBots exist) can pin it
    # via bot_journey_id; an unrecognized/missing id falls back to the default
    # rather than erroring, same fail-open style as the rest of this module.
    bot_journey_id = payload.get("bot_journey_id")
    target_bot_journey = (
        process_agent.bot_journeys.filter(pk=bot_journey_id).first() if bot_journey_id else None
    )
    if target_bot_journey is None:
        target_bot_journey = process_agent.bot_journeys.order_by("order").first()

    for index, lead in enumerate(leads):
        to_number = lead.get("to_number")
        if not to_number:
            skipped.append(lead.get("lead_id") or f"row-{index}")
            continue

        variables = dict(lead.get("params", {}) or {})
        variables["to_number"] = to_number
        if "dnd" in lead:
            variables["dnd"] = lead["dnd"]

        lead_id = lead.get("lead_id") or f"{campaign_id}-{index}"

        executions.append(
            Execution(
                process_agent=process_agent,
                lead_id=lead_id,
                status="pending",
                current_node=NODE_NAME_LEAD_RECEIVED,
                current_bot_journey=target_bot_journey,
                campaign_id=campaign_id,
                variables=variables,
                next_execution=timezone.now(),
            )
        )

    Execution.objects.bulk_create(executions)

    return {
        "campaign_id": campaign_id,
        "created_count": len(executions),
        "skipped": skipped,
    }
