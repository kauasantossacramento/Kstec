from django.apps import AppConfig


class SlaConfig(AppConfig):
    name = "apps.sla"
    verbose_name = "Monitoramento"

    def ready(self):
        from . import abas, painel  # noqa: F401
