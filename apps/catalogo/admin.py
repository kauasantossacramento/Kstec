from django.contrib import admin

from .models import (
    CategoriaCatalogo,
    CodigoNBS,
    CodigoServicoLC116,
    CodigoTributacaoNacional,
    CorrelacaoNBS,
    FaixaPreco,
    ItemCatalogo,
    VariacaoGrafica,
)


@admin.register(CodigoNBS, CodigoServicoLC116, CodigoTributacaoNacional)
class ReferenciaAdmin(admin.ModelAdmin):
    search_fields = ["descricao"]


@admin.register(CorrelacaoNBS)
class CorrelacaoAdmin(admin.ModelAdmin):
    list_display = ["item_lc116", "nbs", "ind_op", "c_class_trib"]
    search_fields = ["item_lc116", "nbs"]


for m in (CategoriaCatalogo, ItemCatalogo, VariacaoGrafica, FaixaPreco):
    admin.site.register(m)
