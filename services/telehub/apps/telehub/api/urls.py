"""API URL routes for the telehub app."""
from rest_framework.routers import DefaultRouter

from .views import (
    DepartmentViewSet,
    IntegrationViewSet,
    NodeTemplateViewSet,
    ProcessAgentViewSet,
)

router = DefaultRouter()
router.register(r"departments", DepartmentViewSet, basename="department")
router.register(r"process-agents", ProcessAgentViewSet, basename="process-agent")
router.register(r"integrations", IntegrationViewSet, basename="integration")
router.register(r"node-templates", NodeTemplateViewSet, basename="node-template")

urlpatterns = router.urls
