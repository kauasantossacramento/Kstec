from django.apps import AppConfig


class OperacaoConfig(AppConfig):
    name = "apps.operacao"
    verbose_name = "Operação"

    def ready(self):
        from . import abas  # noqa: F401
