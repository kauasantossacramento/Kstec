from django.urls import path

from . import views

app_name = "financeiro"
urlpatterns = [path("", views.home, name="home"), path("demonstrativo/", views.demonstrativo, name="demonstrativo"),
    path("extratos/", views.extratos, name="extratos"),
    path("extratos/<uuid:pk>/conciliar/", views.conciliar, name="conciliar"),
    path("lancamentos/<uuid:pk>/baixar/", views.baixar, name="baixar"),
    path("lancamentos/<uuid:pk>/cancelar/", views.cancelar, name="cancelar")]
urlpatterns += [path("recorrencias/<uuid:pk>/gerar/", views.gerar_recorrencia, name="gerar_recorrencia")]
urlpatterns += views.crud.urls(novo=views.CriarLancamento, editar=views.EditarLancamento, detalhe=views.DetalheLancamento)
urlpatterns += views.contas.urls() + views.categorias.urls() + views.centros.urls()
urlpatterns += views.recorrencias.urls()
