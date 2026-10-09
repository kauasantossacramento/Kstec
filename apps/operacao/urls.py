from django.urls import path

from . import views

app_name = "operacao"
urlpatterns = [path("kanban/", views.kanban, name="kanban"),
    path("tarefas/<uuid:pk>/status/", views.status, name="status"),
    path("tarefas/<uuid:pk>/horas/", views.apontar, name="apontar")]
urlpatterns += views.crud.urls(novo=views.CriarTarefa, editar=views.EditarTarefa, detalhe=views.DetalheTarefa)
