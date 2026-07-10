from django.contrib import admin

from .models import (
    AnalyticsEvent,
    Department,
    Execution,
    ExecutionEvent,
    Integration,
    LeadSource,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    ProcessAgent,
    ProcessIntegration,
    QAResult,
    Variable,
    WebhookDefinition,
)

admin.site.register(Department)
admin.site.register(ProcessAgent)
admin.site.register(NodeTemplate)
admin.site.register(NodeInstance)
admin.site.register(NodeConnection)
admin.site.register(LeadSource)
admin.site.register(Integration)
admin.site.register(ProcessIntegration)
admin.site.register(Execution)
admin.site.register(ExecutionEvent)
admin.site.register(QAResult)
admin.site.register(AnalyticsEvent)
admin.site.register(Variable)
admin.site.register(WebhookDefinition)
