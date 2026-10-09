from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from apps.core.crud import Coluna, Crud, DetalheGenerico
from apps.core.forms import FormKS, FormSimples
from apps.core.permissoes import exigir_escrita

from . import services
from .models import (
    CategoriaCatalogo,
    CodigoNBS,
    CodigoServicoLC116,
    CodigoTributacaoNacional,
    FaixaPreco,
    ItemCatalogo,
    ServicoMunicipal,
    VariacaoGrafica,
)


class ItemForm(FormKS):
    servico_municipal = forms.ModelChoiceField(ServicoMunicipal.objects.none(), required=False,
                label="Serviço municipal confirmado", help_text="Selecione um código confirmado do município da empresa.")
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
        self.fields["item_lc116"].queryset = CodigoServicoLC116.objects.exclude(item__endswith=".00")
        self.fields["codigo_tributacao_nacional"].queryset = CodigoTributacaoNacional.objects.filter(vigente=True).exclude(desdobro="00")
        from apps.core import contexto

        empresa = contexto.empresa_atual()
        if empresa:
            self.fields["servico_municipal"].queryset = ServicoMunicipal.objects.filter(
                municipio_ibge=empresa.municipio_ibge, codigo_confirmado=True)

    def clean(self):
        d = super().clean()
        if d.get("natureza") == ItemCatalogo.Natureza.SERVICO and d.get("ncm"):
            self.add_error("ncm", "NCM é só para produtos.")
        municipal = d.get("servico_municipal")
        if municipal:
            if not d.get("item_lc116") or d["item_lc116"].item != municipal.item_lc116:
                self.add_error("servico_municipal", "Serviço municipal incompatível com o item LC 116.")
            else:
                d["codigo_tributacao_municipal"] = municipal.codigo_integracao
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


class CrudMunicipal(Crud):
    def queryset(self, request):
        return super().queryset(request).filter(municipio_ibge=request.empresa.municipio_ibge)


CRUD_MUNICIPAL = CrudMunicipal(ServicoMunicipal, "municipal", "catalogo", caminho="municipais",
    colunas=[Coluna("Item LC 116", "item_lc116", link=True), Coluna("Código API", "codigo_integracao"),
             Coluna("Confirmado", "codigo_confirmado", "bool"), Coluna("Descrição", "descricao")],
    fields=["codigo_integracao", "codigo_confirmado", "fonte"], permitir_criar=False,
    papeis_escrita=["Fiscal"], papeis_leitura=["Fiscal", "Financeiro"], anexos=False,
    busca=["item_lc116", "descricao", "codigo_integracao"], titulo_plural="Códigos municipais",
    ordenacao=["item_lc116"], conversor="int")


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
    conjuntos = {
        "nbs": CodigoNBS.objects.all(),
        "lc": CodigoServicoLC116.objects.exclude(item__endswith=".00"),
        "nacional": CodigoTributacaoNacional.objects.filter(vigente=True).exclude(desdobro="00"),
        "municipal": ServicoMunicipal.objects.filter(municipio_ibge=request.empresa.municipio_ibge),
    }
    ctx = {"q": termo}
    for nome, queryset in conjuntos.items():
        campo = "item" if nome == "lc" else "item_lc116" if nome == "municipal" else "codigo"
        if termo:
            queryset = queryset.filter(Q(descricao__icontains=termo) | Q(**{f"{campo}__icontains": termo}))
        ctx[nome] = Paginator(queryset, 30).get_page(request.GET.get(f"{nome}_pagina"))
    return render(request, "catalogo/tabelas.html", ctx)


@login_required
def importar_tabelas(request):
    from django import forms

    from .importador import importar_arquivo
    from .municipal import importar_municipais

    exigir_escrita(request.user, ["Administrador"])

    class ImportacaoForm(FormSimples):
        tipo = forms.ChoiceField(choices=[("nacional", "Nacional / NBS / correlação — XLSX"),
                                        ("municipal", "Municipal — PDF do Anexo I ou CSV")])
        arquivo = forms.FileField()
        fonte = forms.URLField(label="URL oficial da fonte", required=True)

    form = ImportacaoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        arquivo = form.cleaned_data["arquivo"]
        try:
            if arquivo.size > 20_000_000:
                raise ValidationError("Arquivo acima de 20 MB.")
            if form.cleaned_data["tipo"] == "municipal":
                total = importar_municipais(arquivo.read(), arquivo.name, request.empresa.municipio_ibge,
                                            form.cleaned_data["fonte"])
                resultado = f"{total} referências municipais importadas. Códigos de integração aguardam confirmação."
            else:
                import zipfile

                if not arquivo.name.lower().endswith(".xlsx"):
                    raise ValidationError("Selecione uma planilha XLSX oficial.")
                with zipfile.ZipFile(arquivo) as pacote:
                    if sum(i.file_size for i in pacote.infolist()) > 100_000_000:
                        raise ValidationError("Conteúdo da planilha acima de 100 MB.")
                arquivo.seek(0)
                r = importar_arquivo(arquivo)
                if not (r.lc116 + r.nbs + r.ctribnac + r.correlacoes):
                    raise ValidationError("Nenhum registro reconhecido; confira o arquivo.")
                from apps.core.models import Parametro

                Parametro.definir("fiscal.ultima_importacao", {"fonte": form.cleaned_data["fonte"],
                                  "arquivo": arquivo.name, "resultado": str(r)}, empresa=request.empresa)
                resultado = str(r)
            messages.success(request, resultado)
            return redirect("catalogo:tabelas")
        except Exception as erro:
            form.add_error(None, "; ".join(erro.messages) if isinstance(erro, ValidationError)
                           else f"Importação não concluída ({type(erro).__name__}).")
    return render(request, "catalogo/importar_tabelas.html", {"form": form})
