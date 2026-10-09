from django.urls import path

from . import views

app_name = "faturamento"
urlpatterns = [
    path("", views.home, name="home"),
    path("rotina/", views.rodar_rotina, name="rodar_rotina"),
    path("agendas/nova/", views.agenda_nova, name="agenda_nova"),
    path("agendas/simular/", views.simular, name="simular"),
    path("agendas/<uuid:pk>/", views.agenda, name="agenda"),
    path("agendas/<uuid:pk>/editar/", views.agenda_editar, name="agenda_editar"),
    path("agendas/<uuid:pk>/ativar/", views.agenda_ativar, name="agenda_ativar"),
    path("ciclos/<uuid:pk>/", views.ciclo, name="ciclo"),
    path("ciclos/<uuid:pk>/<slug:acao>/", views.ciclo_acao, name="ciclo_acao"),
    path("recebimentos/", views.recebimentos, name="recebimentos"),
    path("recebimentos/ajustar/<uuid:contrato_pk>/<str:mes>/", views.ajustar_previsao, name="ajustar_previsao"),
]
