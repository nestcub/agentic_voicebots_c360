from django.core.management.base import BaseCommand, CommandError

from ...services.tenancy import find_violations


class Command(BaseCommand):
    help = "Report rows that break the Phase 0 tenancy rules (null org, cross-org relations, duplicate webhook secrets)."

    def handle(self, *args, **options):
        violations = find_violations()
        if not violations:
            self.stdout.write(self.style.SUCCESS("check_tenancy: 0 violations."))
            return
        for rule, pks in violations:
            self.stdout.write(self.style.ERROR(f"{rule}: {len(pks)} row(s) - ids {pks[:50]}"))
        raise CommandError(f"check_tenancy: {len(violations)} rule(s) violated.")
