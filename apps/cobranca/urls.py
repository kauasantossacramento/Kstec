from django.urls import path

from . import views

app_name = "cobranca"
urlpatterns = [
    path("configuracao/", views.configuracao, name="configuracao"),
    path("webhook/", views.webhook, name="webhook"),
    path("gerar/<uuid:lancamento_pk>/", views.gerar, name="gerar"),
    path("<uuid:pk>/atualizar/", views.atualizar, name="atualizar"),
    path("clientes/<uuid:pessoa_pk>/", views.perfil, name="perfil"),
    *views.crud.urls(),
]
