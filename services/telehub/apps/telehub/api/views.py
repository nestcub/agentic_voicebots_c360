from django.core.exceptions import ValidationError
from django.db.models import Count, Min
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from ..models import (
    Department,
    Integration,
    LeadSource,
    NodeTemplate,
    OmnichannelConfig,
    ProcessAgent,
    ProcessIntegration,
    QAResult,
    Variable,
    VoiceBot,
    WebhookDefinition,
)
from ..services import analytics_stats, campaign_launch, outcome_routing
from ..services.dispatcher import dispatch_execution
from ..services.process_agent import (
    create_process_agent_from_wizard,
    sync_voice_bot_to_communication_nodes,
)
from .serializers import (
    BotJourneySerializer,
    CampaignLeadSerializer,
    DepartmentDetailSerializer,
    DepartmentSerializer,
    ExecutionSerializer,
    IntegrationSerializer,
    LeadSourceSerializer,
    NodeConnectionJourneySerializer,
    NodeInstanceJourneySerializer,
    NodeTemplateSerializer,
    OmnichannelConfigSerializer,
    ProcessAgentDetailSerializer,
    ProcessAgentIntegrationSerializer,
    ProcessAgentListSerializer,
    ProcessAgentUpdateSerializer,
    QAResultSerializer,
    VariableSerializer,
    VoiceBotSerializer,
    WebhookDefinitionSerializer,
)

# Wizard QA step toggles (dashboard/components/process-agents/shared.ts's
# QA_FIELDS) — the only keys the qa_config action will write onto the QA
# NodeInstance.config, so an unrecognized key 400s instead of silently
# getting stored where nothing ever reads it.
QA_CONFIG_KEYS = {
    "missing_variables",
    "incorrect_variables",
    "end_call_misfiring",
    "drop_off_analysis",
}

# Wizard Analytics step's "Stats & Summaries" tile toggles (dashboard/
# components/process-agents/shared.ts's STAT_FIELDS) — same allowlist purpose
# as QA_CONFIG_KEYS above, for ProcessAgent.analytics_stats.
ANALYTICS_STAT_KEYS = {
    "initiated_calls",
    "total_call_attempts",
    "picked_up_count",
    "first_response_count",
    "unanswered_calls",
    "drop_off_count",
    "completed_calls",
    "failed_calls",
    "voicemail",
    "not_connected_calls",
    "picked_up_call_rate",
    "average_call_duration",
    "completion_rate",
    "total_cost_of_campaign",
}

VARIABLE_WRITABLE_FIELDS = ("key", "type", "default_value", "label", "required", "source")
WEBHOOK_WRITABLE_FIELDS = ("name", "schema", "status")
OMNICHANNEL_WRITABLE_FIELDS = ("channel", "variables", "whatsapp_template", "whatsapp_curl")


class VoiceBotViewSet(viewsets.ModelViewSet):
    """
    Global CRUD for VoiceBot — the dashboard's /bots page. A VoiceBot is no
    longer owned by any one ProcessAgent (see models.VoiceBot); any
    ProcessAgent's BotJourney can reference any VoiceBot, selected at wizard
    creation time instead of typed in inline.
    """

    queryset = VoiceBot.objects.all().order_by("-created_at")
    serializer_class = VoiceBotSerializer

    def perform_update(self, serializer):
        voice_bot = serializer.save()
        sync_voice_bot_to_communication_nodes(voice_bot)

    def destroy(self, request, *args, **kwargs):
        voice_bot = self.get_object()
        try:
            voice_bot.delete()
        except ProtectedError:
            return Response(
                {"error": "This voice bot is in use by a process agent — detach it first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return DepartmentDetailSerializer
        return DepartmentSerializer


class IntegrationViewSet(viewsets.ModelViewSet):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer


class NodeTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = NodeTemplate.objects.all()
    serializer_class = NodeTemplateSerializer


class ProcessAgentViewSet(viewsets.ModelViewSet):
    queryset = ProcessAgent.objects.select_related("department").all()

    def get_queryset(self):
        queryset = super().get_queryset()
        department_id = self.request.query_params.get("department")
        if department_id is not None:
            queryset = queryset.filter(department_id=department_id)
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return ProcessAgentListSerializer
        if self.action in ("update", "partial_update"):
            return ProcessAgentUpdateSerializer
        return ProcessAgentDetailSerializer

    def create(self, request, *args, **kwargs):
        agent = create_process_agent_from_wizard(request.data)
        serializer = ProcessAgentDetailSerializer(agent)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def journey(self, request, pk=None):
        agent = self.get_object()
        nodes = agent.nodes.all()
        edges = agent.connections.all()
        return Response(
            {
                "nodes": NodeInstanceJourneySerializer(nodes, many=True).data,
                "edges": NodeConnectionJourneySerializer(edges, many=True).data,
            }
        )

    @action(detail=True, methods=["get"])
    def journeys(self, request, pk=None):
        """
        This ProcessAgent's BotJourney(s) (each with its VoiceBot), ordered —
        read-only; a BotJourney is created automatically by the wizard
        (create_process_agent_from_wizard), not through this endpoint. Used by
        the Runs/QA tabs to resolve which bot_journey_id to dispatch through.
        """
        agent = self.get_object()
        return Response(BotJourneySerializer(agent.bot_journeys.all(), many=True).data)

    @action(detail=True, methods=["get"])
    def executions(self, request, pk=None):
        agent = self.get_object()
        return Response(
            ExecutionSerializer(agent.executions.all(), many=True).data
        )

    @action(detail=True, methods=["get"])
    def qa_results(self, request, pk=None):
        agent = self.get_object()
        qa_results = QAResult.objects.filter(execution__process_agent=agent)
        return Response(QAResultSerializer(qa_results, many=True).data)

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        agent = self.get_object()
        return Response(analytics_stats.compute_process_agent_stats(agent))

    @action(detail=True, methods=["get"])
    def analytics(self, request, pk=None):
        """
        Wizard Analytics step's "Dispositions / Variables" — the actual value
        Chat360's post-call webhook filled in for each declared Variable, per
        execution. Read straight off Execution.variables (route_webhook_outcome
        merges each webhook payload into it), not off QAResult.raw_result, so
        this reflects the same source of truth _missing_variables() checks in
        outcome_routing.py. One row per execution, one column per Variable key
        this process declared (any source) — mirrors QA's "expected variables"
        set so the two features describe the same data.
        """
        agent = self.get_object()
        variable_keys = list(agent.variables.order_by("key").values_list("key", flat=True))
        rows = [
            {
                "execution_id": execution.id,
                "lead_id": execution.lead_id,
                "status": execution.status,
                "created_at": execution.created_at.isoformat(),
                "values": {key: (execution.variables or {}).get(key) for key in variable_keys},
            }
            for execution in agent.executions.order_by("-created_at")
        ]
        return Response({"variable_keys": variable_keys, "rows": rows})

    @action(detail=True, methods=["get", "patch"], url_path="qa-config")
    def qa_config(self, request, pk=None):
        """
        GET/PATCH the wizard QA step's toggles (dashboard SettingsTab's
        QA_FIELDS), stored on the primary BotJourney's "QA" NodeInstance.config.
        Scoped to the first BotJourney (order=0 — "Sales Journey" for
        wizard-created agents) since NodeInstance names repeat per journey once
        a ProcessAgent has more than one; Settings only ever edits the primary
        journey's QA behavior for now, matching what SettingsTab already
        displays (it reads the first "QA" node it finds in the combined
        /journey response).
        """
        agent = self.get_object()
        bot_journey = agent.bot_journeys.order_by("order", "id").first()
        node = bot_journey.nodes.filter(name="QA").first() if bot_journey else None

        if request.method.upper() == "GET":
            return Response(node.config if node else {})

        if node is None:
            return Response(
                {"error": "No QA node configured for this process agent yet."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        unknown_keys = set(request.data.keys()) - QA_CONFIG_KEYS
        if unknown_keys:
            return Response(
                {"error": f"Unknown QA config key(s): {', '.join(sorted(unknown_keys))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        node.config = {**node.config, **{k: bool(v) for k, v in request.data.items()}}
        node.save()
        return Response(node.config)

    @action(detail=True, methods=["get", "patch"], url_path="analytics-stats")
    def analytics_stats_config(self, request, pk=None):
        """
        GET/PATCH which Overview stat tiles are enabled (dashboard SettingsTab's
        STAT_FIELDS toggles) — ProcessAgent.analytics_stats is a flat
        {key: bool} JSONB blob with no relational shape, same as the wizard
        Analytics step writes on creation. PATCH merges, so toggling one tile
        doesn't require resending the whole set.
        """
        agent = self.get_object()
        if request.method.upper() == "GET":
            return Response(agent.analytics_stats or {})

        unknown_keys = set(request.data.keys()) - ANALYTICS_STAT_KEYS
        if unknown_keys:
            return Response(
                {"error": f"Unknown analytics stat key(s): {', '.join(sorted(unknown_keys))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        agent.analytics_stats = {
            **(agent.analytics_stats or {}),
            **{k: bool(v) for k, v in request.data.items()},
        }
        agent.save(update_fields=["analytics_stats", "updated_at"])
        return Response(agent.analytics_stats)

    @action(detail=True, methods=["get", "post"], url_path="variables")
    def variables(self, request, pk=None):
        """
        GET: this ProcessAgent's Variable rows (Business Rules + Analytics
        dispositions — same rows ProcessAgentDetailSerializer embeds, exposed
        standalone for the create/list half of Settings' CRUD). POST: creates
        one, validated (required fields, (process_agent, key, source)
        uniqueness) via Variable.full_clean() rather than raising a raw
        IntegrityError on the DB constraint.
        """
        agent = self.get_object()
        if request.method.upper() == "GET":
            return Response(VariableSerializer(agent.variables.all(), many=True).data)

        variable = Variable(process_agent=agent)
        for field in VARIABLE_WRITABLE_FIELDS:
            if field in request.data:
                setattr(variable, field, request.data[field])
        try:
            variable.full_clean()
        except ValidationError as exc:
            return Response({"error": exc.message_dict}, status=status.HTTP_400_BAD_REQUEST)
        variable.save()
        return Response(VariableSerializer(variable).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path="variables/(?P<variable_id>[0-9]+)",
    )
    def variable_detail(self, request, pk=None, variable_id=None):
        agent = self.get_object()
        variable = agent.variables.filter(pk=variable_id).first()
        if variable is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if request.method.upper() == "DELETE":
            variable.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        for field in VARIABLE_WRITABLE_FIELDS:
            if field in request.data:
                setattr(variable, field, request.data[field])
        try:
            variable.full_clean()
        except ValidationError as exc:
            return Response({"error": exc.message_dict}, status=status.HTTP_400_BAD_REQUEST)
        variable.save()
        return Response(VariableSerializer(variable).data)

    @action(
        detail=True,
        methods=["patch"],
        url_path="webhooks/(?P<webhook_id>[0-9]+)",
    )
    def webhook_detail(self, request, pk=None, webhook_id=None):
        """
        PATCH a WebhookDefinition's editable fields — name/schema/status only.
        `url`/`secret` are system-generated at creation (services/
        process_agent.py) and must never change under a live Chat360
        integration, so they're deliberately excluded here.
        """
        agent = self.get_object()
        webhook = agent.webhooks.filter(pk=webhook_id).first()
        if webhook is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        for field in WEBHOOK_WRITABLE_FIELDS:
            if field in request.data:
                setattr(webhook, field, request.data[field])
        webhook.save()
        return Response(WebhookDefinitionSerializer(webhook).data)

    @action(detail=True, methods=["get", "patch"], url_path="omnichannel")
    def omnichannel_config(self, request, pk=None):
        """
        GET/PATCH the wizard Omnichannel step's config — same upsert pattern as
        lead_source() below, since OmnichannelConfig is a nullable
        OneToOneField (a ProcessAgent created without the Omnichannel step has
        none until the first PATCH creates it).
        """
        agent = self.get_object()
        obj = getattr(agent, "omnichannel", None)

        if request.method.upper() == "GET":
            if obj is None:
                return Response({})
            return Response(OmnichannelConfigSerializer(obj).data)

        if obj is None:
            obj = OmnichannelConfig(process_agent=agent)
        for field in OMNICHANNEL_WRITABLE_FIELDS:
            if field in request.data:
                setattr(obj, field, request.data[field])
        obj.save()
        return Response(OmnichannelConfigSerializer(obj).data)

    @action(detail=True, methods=["post"], url_path="integrations")
    def add_integration(self, request, pk=None):
        """
        Attaches an existing Integration to this ProcessAgent (the many-to-many
        join, ProcessIntegration) — creating/editing the Integration itself is
        IntegrationViewSet's job, not this one.
        """
        agent = self.get_object()
        integration_id = request.data.get("integration")
        if not integration_id or not Integration.objects.filter(pk=integration_id).exists():
            return Response(
                {"error": "A valid integration id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        link, _ = ProcessIntegration.objects.get_or_create(
            process_agent=agent, integration_id=integration_id
        )
        return Response(ProcessAgentIntegrationSerializer(link).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["delete"],
        url_path="integrations/(?P<process_integration_id>[0-9]+)",
    )
    def remove_integration(self, request, pk=None, process_integration_id=None):
        agent = self.get_object()
        link = agent.process_integrations.filter(pk=process_integration_id).first()
        if link is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "patch"], url_path="lead-source")
    def lead_source(self, request, pk=None):
        """
        The single LeadSource "entered during agent creation" (the wizard's
        lead_source step), editable afterwards. GET returns the most recently
        created LeadSource row for this agent (or {} if none exists yet — a
        ProcessAgent created without a lead_source step has none). PATCH
        upserts type/configuration/field_mapping onto that row, creating one
        if it doesn't exist yet. This is what launch_campaign() reads from
        when a campaign is launched without an explicit "leads" payload.
        """
        agent = self.get_object()
        obj = agent.lead_sources.order_by("-created_at").first()

        if request.method.upper() == "GET":
            if obj is None:
                return Response({})
            return Response(LeadSourceSerializer(obj).data)

        if obj is None:
            obj = LeadSource(process_agent=agent)
        for field in ("type", "configuration", "field_mapping"):
            if field in request.data:
                setattr(obj, field, request.data[field])
        obj.save()
        return Response(LeadSourceSerializer(obj).data)

    @action(detail=True, methods=["post"], url_path="launch-campaign")
    def launch_campaign(self, request, pk=None):
        agent = self.get_object()
        result = campaign_launch.launch_campaign(agent, request.data)
        return Response(result, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="dispatch-single-call")
    def dispatch_single_call(self, request, pk=None):
        """
        The Runs tab's "Dispatch call" button for a single_source lead source:
        user-supplied @key/value params (Chat360's outbound API expects params
        as an object) go straight into one Execution's variables, and that
        Execution is dispatched to Chat360 synchronously — no waiting on
        run_scheduler's next tick, and no business-hours/DND gating (those are
        scheduler-tick concerns; an explicit manual click bypasses them same
        as it always has). Still goes through campaign_launch.launch_campaign
        (not a raw POST) so the Execution row exists for dlr_id webhook
        correlation, QA, and the Runs tab.

        Optional "bot_journey_id" in the body pins which BotJourney (and so
        which VoiceBot) this test call dispatches through — the Runs tab only
        shows this picker once a process agent has more than one journey;
        omitted defaults to the first journey, same as every other campaign.
        """
        agent = self.get_object()
        params = request.data.get("params", {}) or {}
        if not isinstance(params, dict):
            return Response({"error": "params must be an object"}, status=status.HTTP_400_BAD_REQUEST)

        lead_source = agent.lead_sources.order_by("-created_at").first()
        number = lead_source.configuration.get("number") if lead_source else None
        if not lead_source or lead_source.type != "single_source" or not number:
            return Response(
                {"error": "No single-source lead source with a number configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        campaign_id = f"single-{int(timezone.now().timestamp())}"
        launch_result = campaign_launch.launch_campaign(
            agent,
            {
                "campaign_id": campaign_id,
                "bot_journey_id": request.data.get("bot_journey_id"),
                "leads": [{"to_number": number, "params": params, "lead_id": "single-source"}],
            },
        )
        execution = agent.executions.filter(campaign_id=campaign_id).first()
        if execution is None:
            return Response({"error": "failed to create execution"}, status=status.HTTP_400_BAD_REQUEST)

        dispatch_result = dispatch_execution(execution, is_single_call=True)
        return Response(
            {
                "execution_id": execution.id,
                "created_count": launch_result["created_count"],
                "success": dispatch_result["success"],
                "status_code": dispatch_result["status_code"],
                "error": dispatch_result["error"],
            },
            status=status.HTTP_200_OK if dispatch_result["success"] else status.HTTP_502_BAD_GATEWAY,
        )

    @action(detail=True, methods=["post"], url_path="dispatch-follow-up")
    def dispatch_follow_up(self, request, pk=None):
        """
        The QA tab's "Dispatch Follow-up" button: re-dials the lead from a
        past Execution (identified by "execution_id") through a chosen
        BotJourney/VoiceBot ("bot_journey_id") — e.g. routing a lead who
        needs a follow-up call into the "Follow-up Journey" bot instead of
        whichever bot already called them. Creates a brand-new Execution
        (same to_number, variables carried over from the source execution,
        optionally overridden/extended by "params") rather than mutating the
        original, so the original call's QA/history stays intact and this
        follow-up gets its own row in Runs/QA. Dispatches synchronously, same
        as dispatch_single_call above.
        """
        agent = self.get_object()
        source_execution = agent.executions.filter(pk=request.data.get("execution_id")).first()
        if source_execution is None:
            return Response({"error": "execution not found"}, status=status.HTTP_400_BAD_REQUEST)

        bot_journey_id = request.data.get("bot_journey_id")
        if not agent.bot_journeys.filter(pk=bot_journey_id).exists():
            return Response({"error": "bot journey not found"}, status=status.HTTP_400_BAD_REQUEST)

        to_number = (source_execution.variables or {}).get("to_number")
        if not to_number:
            return Response(
                {"error": "source execution has no to_number to redial"}, status=status.HTTP_400_BAD_REQUEST
            )

        params = {k: v for k, v in (source_execution.variables or {}).items() if k not in ("to_number", "dnd")}
        extra_params = request.data.get("params")
        if isinstance(extra_params, dict):
            params.update(extra_params)

        campaign_id = f"followup-{int(timezone.now().timestamp())}"
        launch_result = campaign_launch.launch_campaign(
            agent,
            {
                "campaign_id": campaign_id,
                "bot_journey_id": bot_journey_id,
                "leads": [
                    {
                        "to_number": to_number,
                        "params": params,
                        "lead_id": f"followup-{source_execution.lead_id}",
                    }
                ],
            },
        )
        execution = agent.executions.filter(campaign_id=campaign_id).first()
        if execution is None:
            return Response({"error": "failed to create follow-up execution"}, status=status.HTTP_400_BAD_REQUEST)

        dispatch_result = dispatch_execution(execution, is_single_call=True)
        return Response(
            {
                "execution_id": execution.id,
                "created_count": launch_result["created_count"],
                "success": dispatch_result["success"],
                "status_code": dispatch_result["status_code"],
                "error": dispatch_result["error"],
            },
            status=status.HTTP_200_OK if dispatch_result["success"] else status.HTTP_502_BAD_GATEWAY,
        )

    @action(detail=True, methods=["get"])
    def campaigns(self, request, pk=None):
        agent = self.get_object()
        rows = (
            agent.executions.exclude(campaign_id="")
            .values("campaign_id")
            .annotate(lead_count=Count("id"), created_at=Min("created_at"))
            .order_by("-created_at")
        )
        return Response(
            [
                {
                    "campaign_id": row["campaign_id"],
                    "lead_count": row["lead_count"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in rows
            ]
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="campaigns/(?P<campaign_id>[^/]+)/leads",
    )
    def campaign_leads(self, request, pk=None, campaign_id=None):
        agent = self.get_object()
        executions = agent.executions.filter(campaign_id=campaign_id)
        return Response(CampaignLeadSerializer(executions, many=True).data)


@api_view(["POST"])
def webhook_intake(request, secret):
    """
    Minimal webhook intake: the real, mounted endpoint that
    WebhookDefinition.url (see services/process_agent.py) actually points to —
    unlike the placeholder that existed before this, this one is live. Looks up
    the WebhookDefinition by secret, correlates to an Execution via
    outcome_routing.find_execution_for_payload (dlr_id if present, otherwise
    the real-world path: normalized contact_no match against the Execution's
    to_number — Chat360's actual post-call payload for this integration never
    includes dlr_id), and routes the resolved Execution's outcome via
    outcome_routing.route_webhook_outcome (Phase D: moves current_node to
    Completed, fires QA/CRM Update always, Callback/Retry conditionally).
    Always acks 200 regardless of whether the secret or payload resolved to
    anything real — external callers must never see a webhook failure from us,
    and never raises.
    """
    webhook = WebhookDefinition.objects.filter(secret=secret).first()
    if webhook is not None:
        payload = dict(request.data) if hasattr(request.data, "items") else {}
        execution = outcome_routing.find_execution_for_payload(
            webhook.process_agent, payload
        )
        if execution is not None:
            outcome_routing.route_webhook_outcome(execution, payload)
    return Response(status=status.HTTP_200_OK)
