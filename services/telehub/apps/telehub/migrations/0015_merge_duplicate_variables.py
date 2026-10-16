from django.db import migrations


def merge_duplicate_variables(apps, schema_editor):
    """
    Variable becomes unique on (process_agent, key) — the old (process_agent,
    key, source) uniqueness allowed the same key as a Business Rules row and an
    Analytics row. Keep the business_rules row (it carries type / default_value
    / required), fold the analytics row's display label into it if it has none,
    and delete the rest. Both use_in_* flags stay True (the column default), so
    QA and Analytics keep seeing every key they saw before.
    """
    Variable = apps.get_model("telehub", "Variable")
    rows_by_key = {}
    for variable in Variable.objects.order_by("process_agent_id", "key", "id"):
        rows_by_key.setdefault((variable.process_agent_id, variable.key), []).append(variable)

    for rows in rows_by_key.values():
        if len(rows) < 2:
            continue
        keeper = next((v for v in rows if v.source == "business_rules"), rows[0])
        for other in rows:
            if other.pk == keeper.pk:
                continue
            if not keeper.label and other.label:
                keeper.label = other.label
            keeper.required = keeper.required or other.required
            other.delete()
        keeper.save()


class Migration(migrations.Migration):

    dependencies = [
        ("telehub", "0014_variable_discovery_flags"),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_variables, migrations.RunPython.noop),
    ]
