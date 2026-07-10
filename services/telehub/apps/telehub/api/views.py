from django.db.models import Count, Min
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from ..models import (
    Department,
    Execution,
    ExecutionEvent,
    Integration,
    NodeTemplate,
    ProcessAgent,
    QAResult,
    WebhookDefinition,
)
from ..services import campaign_launch
from ..services.process_agent import create_process_agent_from_wizard
from .serializers import (
    CampaignLeadSerializer,
    DepartmentDetailSerializer,
    DepartmentSerializer,
    ExecutionSerializer,
    IntegrationSerializer,
    NodeConnectionJourneySerializer,
    NodeInstanceJourneySerializer,
    NodeTemplateSerializer,
    ProcessAgentDetailSerializer,
    ProcessAgentListSerializer,
    ProcessAgentUpdateSerializer,
    QAResultSerializer,
)


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

    @action(detail=True, methods=["post"], url_path="launch-campaign")
    def launch_campaign(self, request, pk=None):
        agent = self.get_object()
        result = campaign_launch.launch_campaign(agent, request.data)
        return Response(result, status=status.HTTP_201_CREATED)

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
    the WebhookDefinition by secret, correlates to an Execution via a `dlr_id`
    in the payload if present, and records the raw payload as an
    ExecutionEvent. Outcome classification / journey routing (moving
    current_node, triggering QA/CRM Update/Retry/Callback) is NOT implemented
    yet — that's the dispatch/schedule engine's Phase D, still to be built.
    Always acks 200 regardless of whether the secret or dlr_id resolved to
    anything real — external callers must never see a webhook failure from us,
    and never raises.
    """
    webhook = WebhookDefinition.objects.filter(secret=secret).first()
    if webhook is not None:
        dlr_id = request.data.get("dlr_id") if hasattr(request.data, "get") else None
        execution = None
        if dlr_id:
            execution = Execution.objects.filter(
                pk=dlr_id, process_agent=webhook.process_agent
            ).first()
        if execution is not None:
            ExecutionEvent.objects.create(
                execution=execution,
                event_type="webhook_received",
                payload=dict(request.data) if hasattr(request.data, "items") else {"raw": str(request.data)},
            )
    return Response(status=status.HTTP_200_OK)
