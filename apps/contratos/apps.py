from django.apps import AppConfig


class ContratosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contratos"
    verbose_name = "Contratos"

    def ready(self):
        from django.urls import reverse

        from apps.core.busca import registrar

        from . import painel  # noqa: F401  (registra agenda/atenção)
        from .models import Contrato

        registrar(rotulo="Contratos", model=Contrato, campos=["numero", "objeto", "cliente__razao_social"],
                  titulo=lambda o: f"Contrato {o.numero}", subtitulo=lambda o: str(o.cliente),
                  url=lambda o: reverse("contratos:contrato_detalhe", args=[o.pk]), icone="file-text")
