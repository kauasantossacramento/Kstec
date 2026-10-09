from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy

from apps.core.crud import Coluna, Crud, DetalheGenerico
from apps.core.forms import FormKS

from . import services
from .models import (
    CategoriaCatalogo,
    CodigoNBS,
    CodigoServicoLC116,
    FaixaPreco,
    ItemCatalogo,
    VariacaoGrafica,
)


class ItemForm(FormKS):
    class Meta:
        model = ItemCatalogo
        fields = ["codigo_interno", "nome", "descricao", "categoria", "natureza", "unidade", "preco_base",
                  "custo_base", "margem_alvo_pct", "item_lc116", "codigo_tributacao_nacional", "nbs",
                  "codigo_tributacao_municipal", "cnae", "aliquota_iss_padrao", "ncm", "prazo_entrega_dias",
                  "permite_venda_avulsa"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["item_lc116"].widget.attrs["data-sugestoes-url"] = reverse_lazy("catalogo:sugestoes")
        self.fields["nbs"].help_text = "Ao escolher o item da LC 116, as NBS correlatas (Anexo VIII) aparecem primeiro."

    def clean(self):
        d = super().clean()
        if d.get("natureza") == ItemCatalogo.Natureza.SERVICO and d.get("ncm"):
            self.add_error("ncm", "NCM é só para produtos.")
        return d


class ItemDetalhe(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        item = self.object
        qtd = 500 if item.faixas.exists() else 1
        ctx.update({"variacoes": item.variacoes.all(), "faixas": item.faixas.all(), "simulacao_qtd": qtd,
                    "simulacao": services.calcular_preco(item, qtd)})
        return ctx


CRUD_ITEM = Crud(
    model=ItemCatalogo, prefixo="item", namespace="catalogo", caminho="itens", titulo="Item do catálogo",
    titulo_plural="Catálogo", subtitulo="Serviços e produtos com códigos fiscais e configurador de preço.",
    colunas=[Coluna("SKU", "codigo_interno", "mono", link=True), Coluna("Nome", "nome"),
             Coluna("Categoria", "categoria"), Coluna("Natureza", "natureza"), Coluna("Unidade", "unidade"),
             Coluna("Preço base", "preco_base", "brl"), Coluna("Apto NFS-e", "apto_nfse", "bool")],
    form_class=ItemForm, busca=["codigo_interno", "nome", "descricao"], filtros=["categoria", "natureza"],
    ordenacao=["nome"], select_related=["categoria"], template_detalhe="catalogo/item_detalhe.html",
    template_form="catalogo/item_form.html",
)
CRUD_CATEGORIA = Crud(
    model=CategoriaCatalogo, prefixo="categoria", namespace="catalogo", feminino=True,
    colunas=[Coluna("Nome", "nome", link=True), Coluna("Tipo", "tipo")], ordenacao=["nome"], anexos=False,
)
CRUD_VARIACAO = Crud(
    model=VariacaoGrafica, prefixo="variacao", namespace="catalogo", feminino=True, caminho="variacoes",
    colunas=[Coluna("Item", "item", link=True), Coluna("Atributo", "atributo"), Coluna("Opção", "opcao"),
             Coluna("Tipo", "acrescimo_tipo"), Coluna("Acréscimo", "acrescimo_valor", "mono")],
    fields=["item", "atributo", "opcao", "acrescimo_tipo", "acrescimo_valor"], select_related=["item"],
    anexos=False, template_form="contratos/form_filho.html",
)
CRUD_FAIXA = Crud(
    model=FaixaPreco, prefixo="faixa", namespace="catalogo", feminino=True,
    colunas=[Coluna("Item", "item", link=True), Coluna("Qtd. mínima", "quantidade_min", "mono"),
             Coluna("Qtd. máxima", "quantidade_max", "mono"), Coluna("Unitário", "preco_unitario", "mono")],
    fields=["item", "quantidade_min", "quantidade_max", "preco_unitario"], select_related=["item"], anexos=False,
    ordenacao=["item", "quantidade_min"], template_form="contratos/form_filho.html",
)


@login_required
def sugestoes(request):
    lc = request.GET.get("valor", "")
    obj = CodigoServicoLC116.objects.filter(pk=lc).first() if lc.isdigit() else None
    return JsonResponse(services.sugestoes_fiscais(obj.item if obj else lc))


@login_required
def preco(request, pk):
    """Preço ao vivo do configurador (HTMX)."""
    item = get_object_or_404(ItemCatalogo, pk=pk, empresa=request.empresa)
    try:
        qtd = Decimal(request.GET.get("quantidade", "1").replace(",", "."))
    except InvalidOperation:
        qtd = Decimal("1")
    variacoes = [v for v in request.GET.getlist("variacoes") if v]
    calc = services.calcular_preco(item, qtd, variacoes)
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"unitario": str(calc["unitario"]), "total": str(calc["total"])})
    return render(request, "catalogo/_preco.html", {"calc": calc, "quantidade": qtd})


@login_required
def tabelas(request):
    termo = request.GET.get("q", "").strip()
    nbs = services.buscar_nbs(termo) if termo else CodigoNBS.objects.all()[:30]
    lc = CodigoServicoLC116.objects.all()[:200]
    return render(request, "catalogo/tabelas.html", {"nbs": nbs, "lc": lc, "q": termo})
