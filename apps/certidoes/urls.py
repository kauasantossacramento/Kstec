from django.urls import path

from . import views

app_name = "certidoes"

urlpatterns = [
    path("", views.home, name="home"),
    path("enviar-lote/", views.lote, name="lote"),
    path("kits/<uuid:pk>/gerar/", views.gerar_kit, name="kit_gerar"),
    *views.CRUD_CERTIDAO.urls(),
    *views.CRUD_TIPO.urls(),
    *views.CRUD_KIT.urls(detalhe=views.KitDetalhe),
]
