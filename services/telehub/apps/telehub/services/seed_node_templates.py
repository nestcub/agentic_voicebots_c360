from typing import Dict

from ..models import NodeTemplate

# Stable lookup keys — other code depends on these strings, do not rename.
SYSTEM_NODE_TEMPLATES = [
    {
        "type": "trigger",
        "category": "trigger",
        "display_name": "Trigger",
        "description": (
            "Examples: Callback, Webhook, Schedule, CRM Event, Timer — the entry "
            "point into a process."
        ),
        "icon": "zap",
        "color": "#f59e0b",
    },
    {
        "type": "logic",
        "category": "logic",
        "display_name": "Logic",
        "description": (
            "Examples: DND Check, Business Hours, Duplicate Check, Lead "
            "Validation, Conditions, Variable Matching."
        ),
        "icon": "git-branch",
        "color": "#8b5cf6",
    },
    {
        "type": "communication",
        "category": "communication",
        "display_name": "Communication",
        "description": (
            "Supports Voice Outbound, Voice Inbound, WhatsApp, SMS, Email — "
            "configured through type selection, not separate node types."
        ),
        "icon": "phone-call",
        "color": "#3b82f6",
    },
    {
        "type": "retry",
        "category": "retry",
        "display_name": "Retry",
        "description": (
            "Configurable Attempts, Delay, Interval, Linear or Exponential "
            "backoff — reusable across any node."
        ),
        "icon": "refresh-cw",
        "color": "#ef4444",
    },
    {
        "type": "routing",
        "category": "routing",
        "display_name": "Routing",
        "description": (
            "Routes execution to another Process, another Department, a Human, "
            "or an External Webhook — the routing engine never knows business "
            "domains, only destinations."
        ),
        "icon": "route",
        "color": "#14b8a6",
    },
    {
        "type": "integration",
        "category": "integration",
        "display_name": "Integration",
        "description": "Examples: CRM, REST API, Webhook, Database, Google Sheets.",
        "icon": "plug",
        "color": "#6366f1",
    },
    {
        "type": "qa",
        "category": "qa",
        "display_name": "QA",
        "description": (
            "Examples: Summary, Sentiment, Hallucination, Lead Quality, "
            "Compliance, Hot Lead Detection, Bot Failure Detection."
        ),
        "icon": "check-circle",
        "color": "#22c55e",
    },
    {
        "type": "output",
        "category": "output",
        "display_name": "Output",
        "description": (
            "Examples: Analytics Event, CRM Update, Notification, Complete, "
            "Failed."
        ),
        "icon": "flag",
        "color": "#64748b",
    },
]


def seed_node_templates() -> Dict[str, "NodeTemplate"]:
    """Idempotent. Returns {type: NodeTemplate} for all 8 system templates."""
    result: Dict[str, "NodeTemplate"] = {}
    for spec in SYSTEM_NODE_TEMPLATES:
        type_key = spec["type"]
        node_template, _ = NodeTemplate.objects.update_or_create(
            type=type_key,
            defaults={
                "category": spec["category"],
                "display_name": spec["display_name"],
                "description": spec["description"],
                "icon": spec["icon"],
                "color": spec["color"],
                "default_config": {},
                "schema": {},
                "is_system": True,
            },
        )
        result[type_key] = node_template
    return result
