from django.urls import path

from . import views_entrega
from .views import (
               CriarNota,
               DetalheNota,
               EditarNota,
               configuracao,
               consultar,
               emitir,
               gerar_recebivel,
               notas,
               perfis,
               receber,
)

app_name = "fiscal"
urlpatterns = [path("configuracao/", configuracao, name="configuracao"),
               path("notas/<uuid:pk>/emitir/", emitir, name="emitir"),
               path("notas/<uuid:pk>/consultar/", consultar, name="consultar")]
urlpatterns += [path("notas/<uuid:pk>/recebivel/", gerar_recebivel, name="gerar_recebivel"),
                path("notas/<uuid:pk>/receber/", receber, name="receber")]
urlpatterns += [path("notas/<uuid:pk>/pdf/", views_entrega.pdf, name="pdf"),
                path("notas/<uuid:pk>/entregas/", views_entrega.entregas, name="entregas"),
                path("entregas/<uuid:pk>/", views_entrega.entrega_revisar, name="entrega_revisar"),
                path("contratos/<uuid:pk>/documentos/", views_entrega.documentos, name="documentos_contrato")]
urlpatterns += notas.urls(novo=CriarNota, editar=EditarNota, detalhe=DetalheNota) + perfis.urls()
