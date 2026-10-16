from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from .services.phone import normalize_digits


class TenantQuerySet(models.QuerySet):
    """Explicit org scoping — no implicit "current org" filtering (see Phase 0 plan §3.5)."""

    def for_org(self, org):
        return self.filter(organization=org)


def _org_fk(related_name):
    return models.ForeignKey(
        "Organization", on_delete=models.PROTECT, related_name=related_name, db_index=True
    )


class Organization(models.Model):
    """A tenant (e.g. Excell Autovista, Hyundai POC). Created by platform staff only."""

    name = models.CharField(max_length=128)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [(ROLE_ADMIN, "Admin"), (ROLE_MEMBER, "Member")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "organization")]

    def __str__(self):
        return f"{self.user_id} @ {self.organization_id} ({self.role})"


class Department(models.Model):
    """A business department (e.g. Automobile > Sales, Healthcare > Billing)."""

    organization = _org_fk("departments")
    objects = TenantQuerySet.as_manager()

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

    organization = _org_fk("process_agents")
    objects = TenantQuerySet.as_manager()

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

    organization = _org_fk("voice_bots")
    objects = TenantQuerySet.as_manager()

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


class PhoneNumber(models.Model):
    """
    One DID of a VoiceBot. A bot has many (a pool); each stage that runs the
    bot is assigned one of them (BotJourney.numbers). `did_key` is the number's
    digits with the India country code stripped, so "+917965311524" and
    "7965311524" are the same number; it is unique within a bot. The same
    number may appear on different bots: calls reach an agent through its own
    webhook URL, never by looking the dialed number up, so a DID is only ever
    used to verify an inbound call and as an outbound caller ID.
    """

    organization = _org_fk("phone_numbers")
    objects = TenantQuerySet.as_manager()

    voice_bot = models.ForeignKey(VoiceBot, on_delete=models.CASCADE, related_name="numbers")
    did = models.CharField(max_length=32)
    did_key = models.CharField(max_length=32, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["voice_bot", "did_key"], name="unique_number_per_voice_bot")
        ]

    def save(self, *args, **kwargs):
        self.did_key = normalize_digits(self.did)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.did


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
    # The one of the VoiceBot's numbers this stage is assigned: outbound dials
    # from it, inbound calls must have dialed it. Empty = automatic: outbound
    # dials from the bot's first number and inbound accepts any of its numbers
    # (every stage before this field existed).
    numbers = models.ManyToManyField(PhoneNumber, blank=True, related_name="journeys")
    name = models.CharField(max_length=128)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.process_agent_id})"


class JourneyTransition(models.Model):
    """
    "When a call in stage `from_journey` ends and these checks pass on its
    variables, hand the lead to stage `to_journey`" — both stages of the same
    process agent. The hand-off creates a new Execution for the target stage
    (services/handoff.py) carrying the call's results as variables.

    `on` picks the moment: "completed" runs when a call's result arrives and
    the lead isn't going to be retried or called back; "retries_exhausted" runs
    when a stage gives up on a lead that never connected. Checks use the same
    language as ChannelRule (services/conditions.py); none = always.
    """

    ON_COMPLETED = "completed"
    ON_RETRIES_EXHAUSTED = "retries_exhausted"
    ON_CHOICES = [(ON_COMPLETED, "Call completed"), (ON_RETRIES_EXHAUSTED, "Retries exhausted")]

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="journey_transitions"
    )
    from_journey = models.ForeignKey(
        BotJourney, on_delete=models.CASCADE, related_name="outgoing_transitions"
    )
    to_journey = models.ForeignKey(
        BotJourney, on_delete=models.CASCADE, related_name="incoming_transitions"
    )
    on = models.CharField(max_length=24, choices=ON_CHOICES, default=ON_COMPLETED)
    priority = models.IntegerField(default=0)
    match = models.CharField(max_length=8, default="all")
    checks = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority", "id"]

    def __str__(self):
        return f"{self.from_journey_id} -> {self.to_journey_id} on {self.on}"


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

    organization = _org_fk("lead_sources")
    objects = TenantQuerySet.as_manager()

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

    organization = _org_fk("integrations")
    objects = TenantQuerySet.as_manager()

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

    organization = _org_fk("executions")
    objects = TenantQuerySet.as_manager()

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
    # The Execution whose result handed this lead to this stage (null for the
    # first stage). Each stage of a lead is its own Execution, so its call, QA
    # and WhatsApp send stay separate — see services/handoff.py.
    parent_execution = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
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

    One row per (process_agent, key). Rows are either declared by hand (the
    wizard / Settings) or discovered from webhook payloads
    (services/variable_discovery.py, `discovered=True`). `use_in_qa` and
    `use_in_analytics` are the user's ticks for which results feed the QA
    missing-variables check and the Analytics tab; declared rows default to
    both on (the behavior before the flags existed), discovered rows to both
    off until ticked. Whether a variable is *sent* to the customer is not a
    flag — it is whatever a channel template's curl placeholders reference.

    `source` is legacy: it used to let the same key exist twice (business
    rules vs analytics) and is kept only so the wizard and dashboard keep
    working until they stop sending it.
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
    use_in_qa = models.BooleanField(default=True)
    use_in_analytics = models.BooleanField(default=True)
    discovered = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    sample_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["process_agent", "key"], name="unique_variable_key_per_agent"
            )
        ]

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
    # Hyundai POC (docs/hyundai-whatsapp-automation-plan.md): one pasted curl
    # per template key ("T1"/"T2"/"T3"), and whether completed inbound calls
    # get one sent automatically. whatsapp_curl above is the pre-POC single
    # curl, still read as T1's fallback.
    whatsapp_curls = models.JSONField(default=dict, blank=True)
    auto_send = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Omnichannel ({self.process_agent_id}) -> {self.channel or '—'}"


class ChannelTemplate(models.Model):
    """
    One message template the agent can send after a call — today always a
    WhatsApp template, held as a pasted Chat360 curl. `name` is the key the
    rest of the system uses ("T1", "T2", ... for agents migrated from the
    three fixed slots; WhatsAppSend.template_key stores it).

    `param_map` refines how curl placeholders resolve; for now it only carries
    fallbacks: {"model_name": {"variable": "model_name", "fallback":
    "model_of_interest"}} reads model_of_interest when model_name is empty.
    `missing_fill`, when set, is sent in place of an empty variable param;
    blank means an empty param blocks the send.
    """

    CHANNEL_WHATSAPP = "whatsapp"

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="channel_templates"
    )
    channel = models.CharField(max_length=32, default=CHANNEL_WHATSAPP)
    name = models.CharField(max_length=64)
    curl = models.TextField(blank=True, default="")
    param_map = models.JSONField(default=dict, blank=True)
    missing_fill = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["process_agent", "name"], name="unique_channel_template_name_per_agent"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.channel}) @ agent {self.process_agent_id}"


class ChannelRule(models.Model):
    """
    "When a call completes, if these checks pass, send this template (or skip
    sending)." Rules are tried in ascending `priority`; the first whose checks
    pass wins. A rule with no checks always matches — use it as the default.

    `checks` is a list of {"variable": key, "op": op[, "value": v]} evaluated
    against the call's variables (see services/conditions.py for the
    operators); `match` says whether all or any of them must pass.
    """

    ACTION_SEND = "send"
    ACTION_SKIP = "skip"
    ACTION_CHOICES = [(ACTION_SEND, "Send"), (ACTION_SKIP, "Skip")]

    MATCH_ALL = "all"
    MATCH_ANY = "any"
    MATCH_CHOICES = [(MATCH_ALL, "All"), (MATCH_ANY, "Any")]

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="channel_rules"
    )
    priority = models.IntegerField(default=0)
    action = models.CharField(max_length=8, choices=ACTION_CHOICES, default=ACTION_SEND)
    template = models.ForeignKey(
        ChannelTemplate, on_delete=models.CASCADE, null=True, blank=True, related_name="rules"
    )
    match = models.CharField(max_length=8, choices=MATCH_CHOICES, default=MATCH_ALL)
    checks = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority", "id"]

    def __str__(self):
        return f"rule {self.priority}: {self.action} @ agent {self.process_agent_id}"


class WhatsAppSend(models.Model):
    """
    One WhatsApp template send for an Execution — automatic (picked by
    services/omnichannel.py, sent by run_scheduler, retried on transient
    failures) or manual (the Calls tab's Send button, sent synchronously).
    At most one automatic send per Execution, so a resent webhook can't
    trigger a second message.
    """

    TRIGGER_AUTO = "auto"
    TRIGGER_MANUAL = "manual"

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    # A mapped variable had no value and the template has no missing_fill:
    # nothing is sent and the scheduler leaves it alone until someone fills the
    # values in (`missing` lists the variable names to fill).
    STATUS_BLOCKED = "blocked"

    execution = models.ForeignKey(
        Execution, on_delete=models.CASCADE, related_name="whatsapp_sends"
    )
    template_key = models.CharField(max_length=64)
    template = models.ForeignKey(
        "ChannelTemplate", on_delete=models.SET_NULL, null=True, blank=True, related_name="sends"
    )
    missing = models.JSONField(default=list, blank=True)
    trigger = models.CharField(max_length=16, default=TRIGGER_AUTO)
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    attempts = models.IntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["execution"],
                condition=models.Q(trigger="auto"),
                name="unique_auto_whatsapp_send_per_execution",
            )
        ]

    def __str__(self):
        return f"WhatsApp {self.template_key} ({self.trigger}) -> execution {self.execution_id}: {self.status}"


class WebhookDefinition(models.Model):
    """An auto-generated webhook (voice bot callbacks, CRM callbacks, ...)."""

    organization = _org_fk("webhooks")
    objects = TenantQuerySet.as_manager()

    process_agent = models.ForeignKey(
        ProcessAgent, on_delete=models.CASCADE, related_name="webhooks"
    )
    name = models.CharField(max_length=128)
    url = models.CharField(max_length=255, blank=True, default="")
    secret = models.CharField(max_length=128, blank=True, default="")
    schema = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["secret"],
                condition=~models.Q(secret=""),
                name="unique_webhook_secret",
            )
        ]

    def __str__(self):
        return self.name
