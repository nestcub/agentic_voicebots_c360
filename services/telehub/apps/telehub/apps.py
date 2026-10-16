from django.apps import AppConfig


class TelehubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.telehub"
    label = "telehub"

    def ready(self):
        from django.db.models.signals import post_save

        from .models import OmnichannelConfig
        from .services import omnichannel

        def sync_channel_templates(sender, instance, created=False, **kwargs):
            # A config created with the old T1/T2/T3 curls (the wizard, older
            # clients) gets matching ChannelTemplates/Rules. Later saves never
            # sync: templates are edited directly now, and a stale legacy curl
            # must not overwrite them. The PATCH endpoint syncs explicitly when
            # a legacy curl is actually sent.
            if created:
                omnichannel.sync_from_legacy_config(instance)

        post_save.connect(
            sync_channel_templates,
            sender=OmnichannelConfig,
            dispatch_uid="telehub_sync_channel_templates",
        )
