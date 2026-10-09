from django.apps import AppConfig


class MensageriaConfig(AppConfig):
    name = "apps.mensageria"
    verbose_name = "WhatsApp"

    def ready(self):
        from .services import assistente  # noqa: F401 — registra as ações confirmáveis
