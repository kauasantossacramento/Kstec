from django.apps import AppConfig


class CertidoesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.certidoes"
    verbose_name = "Certidões"

    def ready(self):
        from . import services  # noqa: F401  (registra agenda/atenção)
