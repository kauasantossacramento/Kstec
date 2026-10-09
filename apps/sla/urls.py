from django.urls import path

from . import views

app_name = "sla"
urlpatterns = [
    path("", views.home, name="home"),
    path("verificar/", views.verificar_todos, name="verificar_todos"),
    path("alertas/", views.alertas, name="alertas"),
    path("alertas/previa/", views.alertas_previa, name="alertas_previa"),
    path("sistemas/<uuid:pk>/verificar/", views.verificar_agora, name="verificar"),
    *views.sistemas.urls(detalhe=views.DetalheSistema),
]
