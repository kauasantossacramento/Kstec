from django.apps import AppConfig


class FinanceiroConfig(AppConfig):
    name = "apps.financeiro"
    verbose_name = "Financeiro"

    def ready(self):
        from . import abas, painel, signals  # noqa: F401
