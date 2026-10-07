import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.telehub.models import Execution
from apps.telehub.services import dispatcher, gating, hyundai_whatsapp

POLLABLE_STATUSES = ["pending", "retry_scheduled", "callback_scheduled"]


def tick() -> int:
    """
    Polls due Executions (next_execution <= now, status in POLLABLE_STATUSES)
    and dispatches the ones that are allowed to go out right now. Returns the
    count of executions actually dispatched (examined in step 4 below) —
    executions skipped for business hours or suppressed for DND don't count.
    """
    processed = 0
    due_executions = Execution.objects.filter(
        next_execution__lte=timezone.now(), status__in=POLLABLE_STATUSES
    )

    for execution in due_executions:
        if not gating.is_within_business_hours(execution):
            # Outside business hours: leave next_execution as-is so it's
            # picked up again next tick once within hours. Don't reschedule
            # forward — that would drift the due time.
            continue

        if gating.is_suppressed_dnc(execution):
            execution.status = "suppressed_dnc"
            execution.next_execution = None
            execution.save()
            continue

        dispatcher.dispatch_execution(execution)
        processed += 1

    return processed


def run_once() -> tuple:
    """One scheduler tick: due outbound calls, then due automatic WhatsApp sends."""
    calls = tick()
    messages = hyundai_whatsapp.process_due_sends()
    return calls, messages


class Command(BaseCommand):
    help = (
        "Polls due Executions and dispatches them (business-hours/DND gated), "
        "then sends due automatic WhatsApp messages."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single tick and exit (for testing/cron), instead of looping forever.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Seconds between ticks when not --once.",
        )

    def handle(self, *args, **options):
        if options["once"]:
            self._report(*run_once())
            return

        interval = options["interval"]
        while True:
            self._report(*run_once())
            time.sleep(interval)

    def _report(self, calls, messages):
        self.stdout.write(
            self.style.SUCCESS(f"Processed {calls} execution(s), {messages} WhatsApp send(s).")
        )
