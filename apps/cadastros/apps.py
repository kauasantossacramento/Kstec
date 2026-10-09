from django.apps import AppConfig


class CadastrosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cadastros"
    verbose_name = "Cadastros"

    def ready(self):
        from django.urls import reverse

        from apps.core.busca import registrar
        from apps.core.validadores import formatar_doc

        from .models import Pessoa

        registrar(rotulo="Clientes e fornecedores", model=Pessoa,
                  campos=["razao_social", "nome_fantasia", "cpf_cnpj"],
                  titulo=lambda o: o.razao_social, subtitulo=lambda o: formatar_doc(o.cpf_cnpj),
                  url=lambda o: reverse("cadastros:pessoa_detalhe", args=[o.pk]), icone="users")
