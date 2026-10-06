from django.contrib.postgres.indexes import GinIndex
from django.db import models


class Department(models.Model):
    """A business department (e.g. Automobile > Sales, Healthcare > Billing)."""

    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=32, blank=True, default="")
    color = models.CharField(max_length=16, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ProcessAgent(models.Model):
    """The core entity of the platform — one Process == one AI agent."""

    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="process_agents"
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, default="draft")
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    # Wizard Analytics step's "Stats & Summaries" tile toggles, e.g.
    # {"initiated_calls": true, "completed_calls": true, ...} — see STAT_FIELDS
    # in dashboard/app/process-agents/new/page.tsx. Display-only config, no
    # relational shape, so a flat JSONB column rather than a table.
    analytics_stats = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class NodeTemplate(models.Model):
    """A system-owned, reusable node capability (e.g. Communication, Retry, QA)."""

    type = models.CharField(max_length=64, unique=True)
    category = models.CharField(max_length=64)
    display_name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=32, blank=True, default="")
    color = models.CharField(max_length=16, blank=True, default="")
    default_config = models.JSONField(default=dict)
    schema = models.JSONField(default=dict)
    is_system = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name


class VoiceBot(models.Model):
    """
    A reusable bot identity/config (bot_name, bot_id, dids, api_url, script,
    webhook_schema) that any ProcessAgent's BotJourney can dispatch calls
    through — managed globally on the dashboard's Bots page, not owned by any
    one ProcessAgent, so the same bot can be selected at creation time by
    several process agents. See BotJourney for how a VoiceBot is wired into
    the call flow.
    """

    label = models.CharField(max_length=128, blank=True, default="")
    communication_type = models.CharField(max_length=32, blank=True, default="")
    bot_name = models.CharField(max_length=128, blank=True, default="")
    bot_id = models.CharField(max_length=128, blank=True, default="")
    dids = models.JSONField(default=list)
    api_url = models.CharField(max_length=255, blank=True, default="")
    script = models.TextField(blank=True, default="")
    webhook_schema = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label or self.bot_name or f"VoiceBot {self.pk}"


class BotJourney(models.Model):
    """
    A named, ordered stage in a ProcessAgent's call orchestration (e.g.
    "Sales Journey", "Follow-up Journey"). Each BotJourney gets its own
    complete copy of the fixed 9-node journey.py graph and is driven by one
    VoiceBot. Journeys on the same ProcessAgent are chained by `order`: when
    an Execution exhausts a journey's Retry budget (see
    services/outcome_routing.py's advance-on-exhaustion logic), it moves into
    the next journey by order rather than the process simply failing —
    letting e.g. a Sales call's unconverted leads automatically flow into a
    Follow-up call with a different bot/script.
    """

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="bot_journeys"
    )
    voice_bot = models.ForeignKey(
        VoiceBot, on_delete=models.PROTECT, related_name="journeys", null=True, blank=True
    )
    name = models.CharField(max_length=128)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.process_agent_id})"


class NodeInstance(models.Model):
    """An actual configured node inside a ProcessAgent's graph."""

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="nodes"
    )
    # Which BotJourney this node belongs to — every node generate_journey()
    # creates is journey-scoped so multiple journeys on one ProcessAgent don't
    # collide on lookups like nodes.get(name="Communication"). Nullable only
    # for pre-multi-journey rows a migration hasn't backfilled yet.
    bot_journey = models.ForeignKey(
        BotJourney, on_delete=models.CASCADE, related_name="nodes", null=True, blank=True
    )
    node_template = models.ForeignKey(
        NodeTemplate, on_delete=models.PROTECT, related_name="+"
    )
    name = models.CharField(max_length=128)
    config = models.JSONField(default=dict)
    position_x = models.FloatField(default=0)
    position_y = models.FloatField(default=0)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class NodeConnection(models.Model):
    """A graph edge between two NodeInstances within a ProcessAgent."""

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="connections"
    )
    source_node = models.ForeignKey(
        NodeInstance, on_delete=models.CASCADE, related_name="outgoing_connections"
    )
    target_node = models.ForeignKey(
        NodeInstance, on_delete=models.CASCADE, related_name="incoming_connections"
    )
    condition = models.CharField(max_length=64, blank=True, default="")
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.source_node_id} -> {self.target_node_id}"


class LeadSource(models.Model):
    """Where leads for a ProcessAgent come from (Meta, Webhook, CRM, ...)."""

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="lead_sources"
    )
    type = models.CharField(max_length=64)
    configuration = models.JSONField(default=dict)
    field_mapping = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} ({self.process_agent_id})"


class Integration(models.Model):
    """An external system (CRM, WhatsApp, REST API, Google Sheets, ...)."""

    name = models.CharField(max_length=128)
    type = models.CharField(max_length=64)
    configuration = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ProcessIntegration(models.Model):
    """Many-to-many join allowing one Integration to be reused across processes."""

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="process_integrations"
    )
    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name="process_integrations"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("process_agent", "integration")]

    def __str__(self):
        return f"{self.process_agent_id} <-> {self.integration_id}"


class Execution(models.Model):
    """A single run of a ProcessAgent for a lead."""

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="executions"
    )
    lead_id = models.CharField(max_length=128)
    status = models.CharField(max_length=32, default="running")
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.IntegerField(null=True, blank=True)
    current_node = models.CharField(max_length=128, blank=True, default="")
    # Which BotJourney this execution's current_node belongs to — needed once
    # a ProcessAgent has more than one journey, since node names ("Retry",
    # "Communication", ...) are no longer unique per process agent. Set on
    # creation (services/campaign_launch.py) to the process agent's first
    # journey, and advanced by services/outcome_routing.py when a journey's
    # retries are exhausted and a next journey exists.
    current_bot_journey = models.ForeignKey(
        BotJourney, on_delete=models.SET_NULL, null=True, blank=True, related_name="executions"
    )
    variables = models.JSONField(default=dict)
    campaign_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    attempt_count = models.IntegerField(default=0)
    next_execution = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            # Lets disposition/analytics filters like variables->>'lead_status'
            # use an index instead of a full scan — no equivalent on SQLite.
            GinIndex(fields=["variables"], name="execution_variables_gin"),
        ]

    def __str__(self):
        return f"Execution {self.id} ({self.lead_id})"


class ExecutionEvent(models.Model):
    """A timeline entry for an Execution (entered node, retry, callback, ...)."""

    execution = models.ForeignKey(
        Execution, on_delete=models.CASCADE, related_name="events"
    )
    node_instance = models.ForeignKey(
        NodeInstance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} @ execution {self.execution_id}"


class QAResult(models.Model):
    """The QA outcome for an Execution — every execution has (at most) one."""

    execution = models.OneToOneField(
        Execution, on_delete=models.CASCADE, related_name="qa_result"
    )
    summary = models.TextField(blank=True, default="")
    sentiment = models.CharField(max_length=32, blank=True, default="")
    hallucination_score = models.FloatField(null=True, blank=True)
    lead_score = models.FloatField(null=True, blank=True)
    compliance_score = models.FloatField(null=True, blank=True)
    bot_failure = models.BooleanField(default=False)
    hot_lead = models.BooleanField(default=False)
    recommendation = models.TextField(blank=True, default="")
    # Populated only when the QA NodeInstance's config has missing_variables=True
    # (wizard QA step) — the process agent's declared Variable keys whose value
    # was absent/empty in execution.variables once the webhook payload merged
    # in. Empty list when the check is off or nothing was missing.
    missing_variables = models.JSONField(default=list)
    raw_result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"QAResult for execution {self.execution_id}"


class AnalyticsEvent(models.Model):
    """A dashboard-facing analytics event (Appointment Booked, Hot Lead, ...)."""

    execution = models.ForeignKey(
        Execution, on_delete=models.CASCADE, related_name="analytics_events"
    )
    event_name = models.CharField(max_length=64)
    event_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.event_name


class Variable(models.Model):
    """A runtime variable exposed by a ProcessAgent (e.g. Customer Name, Phone).

    Shared by the wizard's Business Rules variables and Analytics
    dispositions — `source` disambiguates which step defined a given row,
    since the two mean different things (a business-rules variable has a
    real default_value/required/type; an analytics disposition mainly
    carries a display `label`).
    """

    SOURCE_BUSINESS_RULES = "business_rules"
    SOURCE_ANALYTICS = "analytics"
    SOURCE_CHOICES = [
        (SOURCE_BUSINESS_RULES, "Business Rules"),
        (SOURCE_ANALYTICS, "Analytics"),
    ]

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="variables"
    )
    key = models.CharField(max_length=64)
    type = models.CharField(max_length=32, default="string")
    default_value = models.CharField(max_length=255, blank=True, default="")
    label = models.CharField(max_length=128, blank=True, default="")
    required = models.BooleanField(default=False)
    source = models.CharField(
        max_length=32, choices=SOURCE_CHOICES, default=SOURCE_BUSINESS_RULES
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("process_agent", "key", "source")]

    def __str__(self):
        return self.key


class OmnichannelConfig(models.Model):
    """Wizard Omnichannel step — where to forward captured variables after a call."""

    process_agent = models.OneToOneField(
        ProcessAgent, on_delete=models.CASCADE, related_name="omnichannel"
    )
    channel = models.CharField(max_length=32, blank=True, default="")
    variables = models.JSONField(default=list)
    whatsapp_template = models.CharField(max_length=128, blank=True, default="")
    whatsapp_curl = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Omnichannel ({self.process_agent_id}) -> {self.channel or '—'}"


class WebhookDefinition(models.Model):
    """An auto-generated webhook (voice bot callbacks, CRM callbacks, ...)."""

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="webhooks"
    )
    name = models.CharField(max_length=128)
    url = models.CharField(max_length=255, blank=True, default="")
    secret = models.CharField(max_length=128, blank=True, default="")
    schema = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
