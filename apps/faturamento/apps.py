from django.apps import AppConfig


class FaturamentoConfig(AppConfig):
    name = "apps.faturamento"
    verbose_name = "Faturamento recorrente"

    def ready(self):
        from . import abas, painel  # noqa: F401
