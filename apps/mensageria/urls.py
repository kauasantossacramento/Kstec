from django.urls import path

from . import views

app_name = "whatsapp"
urlpatterns = [
    path("", views.home, name="home"),
    path("status/", views.status, name="status"),
    path("configuracao/", views.configuracao, name="configuracao"),
    path("teste/", views.teste, name="teste"),
    path("rotinas/", views.rotinas, name="rotinas"),
    path("reconectar/", views.reconectar, name="reconectar"),
    path("lotes/<uuid:pk>/<slug:acao>/", views.lote_acao, name="lote_acao"),
    path("mensagens/<uuid:pk>/reenviar/", views.reenviar, name="reenviar"),
    path("clientes/<uuid:pessoa_pk>/contato/", views.contato_rapido, name="contato_rapido"),
    *views.contatos.urls(),
    *views.mensagens.urls(),
]
