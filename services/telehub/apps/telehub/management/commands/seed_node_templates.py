from django.core.management.base import BaseCommand

from ...models import NodeTemplate
from ...services.seed_node_templates import seed_node_templates


class Command(BaseCommand):
    help = "Idempotently seed the 8 system NodeTemplate rows."

    def handle(self, *args, **options):
        before_ids = set(NodeTemplate.objects.values_list("id", flat=True))
        templates = seed_node_templates()
        after = NodeTemplate.objects.filter(type__in=templates.keys())
        created = after.exclude(id__in=before_ids).count()
        updated = len(templates) - created
        self.stdout.write(
            self.style.SUCCESS(
                f"NodeTemplate seed complete: {created} created, {updated} updated "
                f"({len(templates)} total system templates)."
            )
        )
