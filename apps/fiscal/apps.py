from django.apps import AppConfig


class FiscalConfig(AppConfig):
    name = "apps.fiscal"
    verbose_name = "Fiscal"

    def ready(self):
        from . import abas  # noqa: F401
