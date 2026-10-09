from django.apps import AppConfig


class CatalogoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalogo"
    verbose_name = "Catálogo"

    def ready(self):
        from django.urls import reverse

        from apps.core.busca import registrar

        from .models import ItemCatalogo

        registrar(rotulo="Catálogo", model=ItemCatalogo, campos=["codigo_interno", "nome"],
                  titulo=lambda o: o.nome, subtitulo=lambda o: o.codigo_interno,
                  url=lambda o: reverse("catalogo:item_detalhe", args=[o.pk]), icone="package")
