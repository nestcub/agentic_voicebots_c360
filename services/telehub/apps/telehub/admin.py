from django.contrib import admin

from .models import (
    AnalyticsEvent,
    BotJourney,
    Department,
    Execution,
    ExecutionEvent,
    Integration,
    LeadSource,
    Membership,
    NodeConnection,
    NodeInstance,
    NodeTemplate,
    OmnichannelConfig,
    Organization,
    ProcessAgent,
    ProcessIntegration,
    QAResult,
    Variable,
    VoiceBot,
    WebhookDefinition,
    WhatsAppSend,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "created_at")
    list_filter = ("organization", "role")


class TenantAdmin(admin.ModelAdmin):
    list_filter = ("organization",)


for _model in (Department, ProcessAgent, VoiceBot, Integration, LeadSource, WebhookDefinition, Execution):
    admin.site.register(_model, TenantAdmin)

admin.site.register(BotJourney)
admin.site.register(NodeTemplate)
admin.site.register(NodeInstance)
admin.site.register(NodeConnection)
admin.site.register(ProcessIntegration)
admin.site.register(ExecutionEvent)
admin.site.register(QAResult)
admin.site.register(AnalyticsEvent)
admin.site.register(Variable)
admin.site.register(OmnichannelConfig)
admin.site.register(WhatsAppSend)
