"""API URL routes for the telehub app."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DepartmentViewSet,
    IntegrationViewSet,
    NodeTemplateViewSet,
    ProcessAgentViewSet,
    VoiceBotViewSet,
    webhook_intake,
)

router = DefaultRouter()
router.register(r"departments", DepartmentViewSet, basename="department")
router.register(r"process-agents", ProcessAgentViewSet, basename="process-agent")
router.register(r"integrations", IntegrationViewSet, basename="integration")
router.register(r"node-templates", NodeTemplateViewSet, basename="node-template")
router.register(r"voice-bots", VoiceBotViewSet, basename="voice-bot")

urlpatterns = [
    path("webhooks/<str:secret>/", webhook_intake, name="webhook-intake"),
] + router.urls
