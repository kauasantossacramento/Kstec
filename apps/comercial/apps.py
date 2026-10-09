from django.apps import AppConfig


class ComercialConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.comercial"
    verbose_name = "Comercial"

    def ready(self):
        from django.urls import reverse

        from apps.core.busca import registrar

        from . import services  # noqa: F401
        from .models import Orcamento

        registrar(rotulo="Orçamentos", model=Orcamento,
                  campos=["numero", "cliente__razao_social", "cliente_avulso_nome"],
                  titulo=lambda o: o.numero, subtitulo=lambda o: o.nome_cliente,
                  url=lambda o: reverse("comercial:orcamento_detalhe", args=[o.pk]), icone="briefcase")
