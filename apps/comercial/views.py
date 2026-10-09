from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalogo.models import ItemCatalogo
from apps.core.crud import Coluna, Crud, DetalheGenerico
from apps.core.forms import FormKS, FormSimples
from apps.core.permissoes import exigir_escrita

from . import services
from .models import ItemOrcamento, Orcamento, Venda


class OrcamentoForm(FormKS):
    class Meta:
        model = Orcamento
        fields = ["cliente", "cliente_avulso_nome", "cliente_avulso_doc", "cliente_avulso_contato", "data", "validade",
                  "condicoes_pagamento", "prazo_entrega", "desconto_tipo", "desconto_valor", "observacoes"]

    campos_doc = ("cliente_avulso_doc",)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["cliente"].required = False
        self.fields["cliente"].help_text = "Ou preencha os campos de cliente avulso."
        if not self.instance.pk:
            self.fields["validade"].initial = timezone.localdate() + timezone.timedelta(days=15)

    def clean(self):
        d = super().clean()
        if not d.get("cliente") and not d.get("cliente_avulso_nome"):
            self.add_error("cliente", "Escolha um cliente ou informe o nome do cliente avulso.")
        return d

    def save(self, commit=True):
        o = super().save(commit=commit)
        if o.pk:
            o.recalcular()
        return o


class ItemOrcamentoForm(FormSimples):
    item_catalogo = forms.ModelChoiceField(queryset=ItemCatalogo.objects.filter(ativo=True), required=False,
                                           label="Item do catálogo")
    descricao = forms.CharField(max_length=500, required=False, label="Descrição")
    quantidade = forms.DecimalField(max_digits=12, decimal_places=3, initial=1)
    preco_unitario = forms.DecimalField(max_digits=14, decimal_places=4, required=False, label="Preço unitário",
                                        help_text="Em branco: calculado pela faixa + variações.")

    def clean(self):
        d = super().clean()
        if not d.get("item_catalogo") and not (d.get("descricao") and d.get("preco_unitario") is not None):
            raise forms.ValidationError("Escolha um item do catálogo ou informe descrição e preço.")
        return d


class OrcamentoDetalhe(DetalheGenerico):
    def get_template_names(self):
        return ["comercial/orcamento_detalhe.html"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        o = self.object
        passo = 2 if o.status == Orcamento.Status.RASCUNHO and not o.itens.exists() else (
            3 if o.status == Orcamento.Status.RASCUNHO else 4)
        ctx.update({"itens": o.itens.select_related("item_catalogo"), "form_item": ItemOrcamentoForm(),
                    "link": services.link_publico(o), "passo": passo,
                    "catalogo": ItemCatalogo.objects.filter(empresa=o.empresa, ativo=True).prefetch_related("variacoes")})
        return ctx


CRUD_ORCAMENTO = Crud(
    model=Orcamento, prefixo="orcamento", namespace="comercial",
    subtitulo="Orçamentos com aprovação pelo cliente via link.",
    colunas=[Coluna("Número", "numero", "mono", link=True), Coluna("Cliente", "nome_cliente"),
             Coluna("Data", "data", "data"), Coluna("Validade", "validade", "data"), Coluna("Total", "total", "brl"),
             Coluna("Status", "status", "status", "Orcamento")],
    form_class=OrcamentoForm, busca=["numero", "cliente__razao_social", "cliente_avulso_nome"], filtros=["status"],
    ordenacao=["-data", "-numero"], select_related=["cliente"], template_form="comercial/orcamento_form.html",
)
CRUD_VENDA = Crud(
    model=Venda, prefixo="venda", namespace="comercial", feminino=True,
    colunas=[Coluna("Número", "numero", "mono", link=True), Coluna("Cliente", "cliente"), Coluna("Data", "data", "data"),
             Coluna("Total", "total", "brl"), Coluna("Status", "status", "status", "Venda")],
    fields=["status", "gera_nf", "parcelas", "primeiro_vencimento", "observacoes"], filtros=["status"],
    ordenacao=["-data"], select_related=["cliente"], permitir_criar=False, template_detalhe="comercial/venda_detalhe.html",
)


class VendaDetalhe(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["itens"] = self.object.itens.select_related("item_catalogo")
        ctx["acoes_venda"] = []
        return ctx


def _orc(request, pk):
    return get_object_or_404(Orcamento, pk=pk, empresa=request.empresa)


@login_required
@require_POST
def item_adicionar(request, pk):
    exigir_escrita(request.user)
    o = _orc(request, pk)
    form = ItemOrcamentoForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.adicionar_item(o, d.get("item_catalogo"), d["quantidade"], request.POST.getlist("variacoes"),
                                    d.get("descricao") or "", d.get("preco_unitario"))
            messages.success(request, "Item adicionado.")
        except services.TransicaoInvalida as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "; ".join(str(e) for e in form.non_field_errors()) or "Confira o item.")
    return redirect(reverse("comercial:orcamento_detalhe", args=[pk]))


@login_required
@require_POST
def item_remover(request, pk, item_pk):
    exigir_escrita(request.user)
    o = _orc(request, pk)
    if o.editavel:
        ItemOrcamento.objects.filter(pk=item_pk, orcamento=o).delete()
        o.recalcular()
    return redirect(reverse("comercial:orcamento_detalhe", args=[pk]))


@login_required
def variacoes_item(request):
    item = ItemCatalogo.objects.filter(pk=request.GET.get("item_catalogo") or None, empresa=request.empresa).first()
    return render(request, "comercial/_variacoes.html", {"item": item})


@login_required
def preco_item(request):
    item = ItemCatalogo.objects.filter(pk=request.GET.get("item_catalogo") or None, empresa=request.empresa).first()
    if not item:
        return render(request, "catalogo/_preco.html", {"calc": {"detalhes": [], "unitario": 0, "total": 0},
                                                        "quantidade": 0})
    try:
        qtd = Decimal((request.GET.get("quantidade") or "1").replace(".", "").replace(",", "."))
    except InvalidOperation:
        qtd = Decimal("1")
    from apps.catalogo.services import calcular_preco

    return render(request, "catalogo/_preco.html", {"calc": calcular_preco(item, qtd, request.GET.getlist("variacoes")),
                                                    "quantidade": qtd})


@login_required
@require_POST
def enviar(request, pk):
    exigir_escrita(request.user)
    o = _orc(request, pk)
    try:
        services.enviar(o, request.POST.get("email") or None)
        messages.success(request, "Orçamento enviado. Link público disponível para copiar.")
    except services.TransicaoInvalida as e:
        messages.error(request, str(e))
    return redirect(reverse("comercial:orcamento_detalhe", args=[pk]))


@login_required
@require_POST
def pdf(request, pk):
    o = _orc(request, pk)
    anexo = services.gerar_pdf(o)
    return redirect(reverse("core:anexo_baixar", args=[anexo.pk]) + "?ver=1")


@login_required
@require_POST
def converter(request, pk):
    exigir_escrita(request.user)
    o = _orc(request, pk)
    try:
        venda = services.converter_em_venda(o, int(request.POST.get("parcelas") or 1))
        messages.success(request, f"Venda {venda.numero} criada.")
        return redirect(reverse("comercial:venda_detalhe", args=[venda.pk]))
    except services.TransicaoInvalida as e:
        messages.error(request, str(e))
        return redirect(reverse("comercial:orcamento_detalhe", args=[pk]))


@login_required
@require_POST
def marcar_recusado(request, pk):
    exigir_escrita(request.user)
    o = _orc(request, pk)
    o.status = Orcamento.Status.RECUSADO
    o.save(update_fields=["status"])
    return redirect(reverse("comercial:orcamento_detalhe", args=[pk]))


# ---------------------------------------------------------------------------
# Página pública (/o/<token>/) — sem login
# ---------------------------------------------------------------------------


def _ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")


def publico(request, token):
    o = get_object_or_404(Orcamento, token_publico=token)
    if o.status in (Orcamento.Status.RASCUNHO,):
        return render(request, "comercial/publico_indisponivel.html", status=404)
    erro = None
    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()
        try:
            if request.POST.get("acao") == "aprovar":
                if len(nome) < 3:
                    raise services.TransicaoInvalida("Informe seu nome completo para aprovar.")
                services.aprovar(o, nome, _ip(request))
            elif request.POST.get("acao") == "ajuste":
                texto = (request.POST.get("texto") or "").strip()
                if not texto:
                    raise services.TransicaoInvalida("Descreva o ajuste desejado.")
                services.solicitar_ajuste(o, nome or "Cliente", texto)
                o.ajuste_enviado = True
            o.refresh_from_db()
        except services.TransicaoInvalida as e:
            erro = str(e)
    else:
        services.registrar_visualizacao(o)
    return render(request, "comercial/publico.html", {"o": o, "itens": o.itens.all(), "erro": erro,
                                                      "empresa": o.empresa,
                                                      "ajuste_enviado": getattr(o, "ajuste_enviado", False)})
