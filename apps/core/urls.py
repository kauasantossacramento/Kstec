from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("entrar/", views.Login.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("mfa/configurar/", views.mfa_configurar, name="mfa_configurar"),
    path("mfa/verificar/", views.mfa_verificar, name="mfa_verificar"),
    path("perfil/", views.perfil, name="perfil"),
    path("perfil/tema/", views.tema, name="tema"),
    path("notificacoes/", views.notificacoes, name="notificacoes"),
    path("notificacoes/<uuid:pk>/", views.notificacao_abrir, name="notificacao_abrir"),
    path("busca/", views.busca, name="busca"),
    path("anexos/<uuid:pk>/", views.anexo_baixar, name="anexo_baixar"),
    path("consulta/cnpj/", views.consulta_cnpj, name="consulta_cnpj"),
    path("consulta/cep/", views.consulta_cep, name="consulta_cep"),
    path("_componentes/", views.componentes, name="componentes"),
    path("configuracoes/", views.configuracoes, name="configuracoes"),
    path("configuracoes/empresa/", views.empresa_editar, name="empresa"),
    *views.CRUD_USUARIO.urls(),
    *views.CRUD_PARAMETRO.urls(),
    *views.CRUD_LOG.urls(),
]
