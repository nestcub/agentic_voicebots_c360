"""Cross-relation org-consistency rules (Phase 0 plan section 3.3), shared by check_tenancy and tests."""

from django.db.models import Count, F

from ..models import (
    BotJourney,
    Department,
    Execution,
    Integration,
    JourneyTransition,
    LeadSource,
    PhoneNumber,
    ProcessAgent,
    ProcessIntegration,
    VoiceBot,
    WebhookDefinition,
)

TENANT_MODELS = [
    Department,
    ProcessAgent,
    VoiceBot,
    PhoneNumber,
    Integration,
    LeadSource,
    WebhookDefinition,
    Execution,
]


def find_violations():
    """Return a list of (rule, [pk, ...]) for every rule that has offending rows."""
    checks = [
        (f"{m.__name__}.organization is NULL", m.objects.filter(organization__isnull=True))
        for m in TENANT_MODELS
    ]
    checks += [
        (
            "ProcessAgent.organization != department.organization",
            ProcessAgent.objects.exclude(organization=F("department__organization")),
        ),
        (
            "BotJourney.voice_bot.organization != process_agent.organization",
            BotJourney.objects.filter(voice_bot__isnull=False).exclude(
                voice_bot__organization=F("process_agent__organization")
            ),
        ),
        (
            "ProcessIntegration.integration.organization != process_agent.organization",
            ProcessIntegration.objects.exclude(
                integration__organization=F("process_agent__organization")
            ),
        ),
        (
            "Execution.organization != process_agent.organization",
            Execution.objects.exclude(organization=F("process_agent__organization")),
        ),
        (
            "PhoneNumber.organization != voice_bot.organization",
            PhoneNumber.objects.exclude(organization=F("voice_bot__organization")),
        ),
        (
            "BotJourney.numbers includes a number of a different voice bot",
            BotJourney.numbers.through.objects.exclude(phonenumber__voice_bot=F("botjourney__voice_bot")),
        ),
        (
            "JourneyTransition stages belong to a different process agent",
            JourneyTransition.objects.exclude(
                from_journey__process_agent=F("process_agent"), to_journey__process_agent=F("process_agent")
            ),
        ),
        (
            "Execution.parent_execution belongs to a different process agent",
            Execution.objects.filter(parent_execution__isnull=False).exclude(
                parent_execution__process_agent=F("process_agent")
            ),
        ),
        (
            "LeadSource.organization != process_agent.organization",
            LeadSource.objects.exclude(organization=F("process_agent__organization")),
        ),
        (
            "WebhookDefinition.organization != process_agent.organization",
            WebhookDefinition.objects.exclude(organization=F("process_agent__organization")),
        ),
    ]
    out = [(rule, list(qs.values_list("pk", flat=True))) for rule, qs in checks]

    dup_secrets = [
        d["secret"]
        for d in WebhookDefinition.objects.exclude(secret="")
        .values("secret")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    ]
    dup_ids = list(
        WebhookDefinition.objects.filter(secret__in=dup_secrets).values_list("pk", flat=True)
    )
    out.append(("WebhookDefinition.secret is duplicated", dup_ids))
    return [(rule, pks) for rule, pks in out if pks]
