from django.urls import path

from . import views

app_name = "comercial"

urlpatterns = [
    path("orcamentos/<uuid:pk>/itens/", views.item_adicionar, name="item_adicionar"),
    path("orcamentos/<uuid:pk>/itens/<uuid:item_pk>/remover/", views.item_remover, name="item_remover"),
    path("orcamentos/<uuid:pk>/enviar/", views.enviar, name="enviar"),
    path("orcamentos/<uuid:pk>/pdf/", views.pdf, name="pdf"),
    path("orcamentos/<uuid:pk>/converter/", views.converter, name="converter"),
    path("orcamentos/<uuid:pk>/recusado/", views.marcar_recusado, name="recusado"),
    path("configurador/variacoes/", views.variacoes_item, name="variacoes"),
    path("configurador/preco/", views.preco_item, name="preco"),
    *views.CRUD_ORCAMENTO.urls(detalhe=views.OrcamentoDetalhe),
    *views.CRUD_VENDA.urls(detalhe=views.VendaDetalhe),
]
