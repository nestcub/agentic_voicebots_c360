from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Department, Integration, NodeTemplate, ProcessAgent, QAResult
from ..services.process_agent import create_process_agent_from_wizard
from .serializers import (
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
