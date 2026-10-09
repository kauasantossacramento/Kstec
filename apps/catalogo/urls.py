from django.urls import path

from . import views

app_name = "catalogo"

urlpatterns = [
    path("sugestoes/", views.sugestoes, name="sugestoes"),
    path("tabelas/", views.tabelas, name="tabelas"),
    path("tabelas/importar/", views.importar_tabelas, name="importar_tabelas"),
    path("itens/<uuid:pk>/preco/", views.preco, name="preco"),
    *views.CRUD_ITEM.urls(detalhe=views.ItemDetalhe),
    *views.CRUD_CATEGORIA.urls(),
    *views.CRUD_VARIACAO.urls(),
    *views.CRUD_FAIXA.urls(),
    *views.CRUD_MUNICIPAL.urls(),
]
