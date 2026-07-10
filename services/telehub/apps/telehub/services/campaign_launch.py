from ..models import Execution

NODE_NAME_LEAD_RECEIVED = "Lead Received"


def launch_campaign(process_agent, payload: dict) -> dict:
    """
    payload: {"campaign_id": str, "leads": [{"to_number": str, "params": dict, "dnd"?: str, "lead_id"?: str}]}

    Bulk-creates one Execution per lead: status="pending", current_node="Lead Received",
    campaign_id=payload["campaign_id"], variables = params merged with {"to_number": to_number}
    and {"dnd": dnd} if the lead dict has a "dnd" key. lead_id = lead.get("lead_id") or
    f"{campaign_id}-{index}". Rows missing to_number are skipped (not created), their
    lead_id (or "row-{index}" if absent) collected into the returned skipped list — never
    silently dropped without being accounted for. Uses Execution.objects.bulk_create for
    the actual insert. Returns {"campaign_id": str, "created_count": int, "skipped": list[str]}.
    """
    campaign_id = payload.get("campaign_id", "")
    leads = payload.get("leads", []) or []

    executions = []
    skipped = []

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
                campaign_id=campaign_id,
                variables=variables,
            )
        )

    Execution.objects.bulk_create(executions)

    return {
        "campaign_id": campaign_id,
        "created_count": len(executions),
        "skipped": skipped,
    }
