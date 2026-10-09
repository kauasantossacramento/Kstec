from .views import CRUD_CONTATO, CRUD_PESSOA, PessoaDetalhe

app_name = "cadastros"

urlpatterns = [
    *CRUD_PESSOA.urls(detalhe=PessoaDetalhe),
    *CRUD_CONTATO.urls(),
]
