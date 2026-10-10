from django.urls import path

from . import views

app_name = "contratos"

urlpatterns = [
    *views.CRUD_ADITIVO.urls(),
    *views.CRUD_ITEM.urls(),
    *views.CRUD_EMPENHO.urls(),
    *views.CRUD_COMPETENCIA.urls(),
    path("<uuid:pk>/gerar-competencias/", views.gerar_competencias, name="gerar_competencias"),
    path("<uuid:pk>/situacao/", views.situacao, name="situacao"),
    *views.CRUD_CONTRATO.urls(lista=views.ContratoLista, detalhe=views.ContratoHub),
]
