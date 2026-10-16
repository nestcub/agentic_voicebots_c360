from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...models import (
    Department,
    Execution,
    Integration,
    PhoneNumber,
    LeadSource,
    Organization,
    ProcessAgent,
    ProcessIntegration,
    VoiceBot,
    WebhookDefinition,
)


class Command(BaseCommand):
    help = (
        "Move departments (with their process agents, executions, lead sources and webhooks, "
        "plus the bots/integrations those agents use) into an organization. Use --dry-run first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--org", required=True, help="Target organization slug (created if missing).")
        parser.add_argument("--org-name", default="", help="Display name when creating the org.")
        parser.add_argument("--department", type=int, action="append", required=True, dest="departments")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, org, org_name, departments, dry_run, **options):
        found = set(Department.objects.filter(pk__in=departments).values_list("pk", flat=True))
        missing = set(departments) - found
        if missing:
            raise CommandError(f"Unknown department id(s): {sorted(missing)}")

        agents = ProcessAgent.objects.filter(department_id__in=found)
        agent_ids = set(agents.values_list("pk", flat=True))

        bot_ids = set(
            VoiceBot.objects.filter(journeys__process_agent_id__in=agent_ids).values_list("pk", flat=True)
        )
        integration_ids = set(
            Integration.objects.filter(
                process_integrations__process_agent_id__in=agent_ids
            ).values_list("pk", flat=True)
        )

        # A bot/integration used by a moved agent AND by an agent staying in another org can't move.
        shared_bots = {
            bot.pk
            for bot in VoiceBot.objects.filter(pk__in=bot_ids)
            if bot.journeys.exclude(process_agent_id__in=agent_ids)
            .exclude(process_agent__organization__slug=org)
            .exists()
        }
        shared_integrations = set(
            ProcessIntegration.objects.filter(integration_id__in=integration_ids)
            .exclude(process_agent_id__in=agent_ids)
            .exclude(process_agent__organization__slug=org)
            .values_list("integration_id", flat=True)
        )
        if shared_bots or shared_integrations:
            raise CommandError(
                "Shared across orgs - duplicate them or pick one owner, then re-run. "
                f"VoiceBot ids: {sorted(shared_bots)}; Integration ids: {sorted(shared_integrations)}"
            )

        plan = [
            ("Department", len(found)),
            ("ProcessAgent", len(agent_ids)),
            ("Execution", Execution.objects.filter(process_agent_id__in=agent_ids).count()),
            ("LeadSource", LeadSource.objects.filter(process_agent_id__in=agent_ids).count()),
            ("WebhookDefinition", WebhookDefinition.objects.filter(process_agent_id__in=agent_ids).count()),
            ("VoiceBot", len(bot_ids)),
            ("Integration", len(integration_ids)),
        ]
        self.stdout.write(f"Target org: {org}  (departments {sorted(found)})")
        for label, n in plan:
            self.stdout.write(f"  {label}: {n} row(s) -> {org}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - nothing written."))
            return

        with transaction.atomic():
            target, _ = Organization.objects.get_or_create(
                slug=org, defaults={"name": org_name or org.replace("-", " ").title()}
            )
            Department.objects.filter(pk__in=found).update(organization=target)
            agents.update(organization=target)
            Execution.objects.filter(process_agent_id__in=agent_ids).update(organization=target)
            LeadSource.objects.filter(process_agent_id__in=agent_ids).update(organization=target)
            WebhookDefinition.objects.filter(process_agent_id__in=agent_ids).update(organization=target)
            VoiceBot.objects.filter(pk__in=bot_ids).update(organization=target)
            PhoneNumber.objects.filter(voice_bot_id__in=bot_ids).update(organization=target)
            Integration.objects.filter(pk__in=integration_ids).update(organization=target)
        self.stdout.write(self.style.SUCCESS("Done. Now run: manage.py check_tenancy"))
