from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.crud import Coluna, Crud, DetalheGenerico, ListaGenerica
from apps.core.forms import FormKS
from apps.core.permissoes import exigir_escrita

from . import services
from .abas import ABAS, PROVEDORES
from .models import Aditivo, Competencia, Contrato, Empenho, ItemContrato


class ContratoForm(FormKS):
    class Meta:
        model = Contrato
        fields = ["numero", "cliente", "objeto", "modalidade", "processo_administrativo", "fundamento_legal",
                  "data_assinatura", "vigencia_inicio", "vigencia_fim", "valor_global", "valor_mensal",
                  "forma_faturamento", "dia_faturamento", "prazo_pagamento_dias", "indice_reajuste",
                  "data_base_reajuste", "status", "gestor_contrato", "fiscal_contrato", "discriminacao_padrao",
                  "exige_relatorio_atividades", "exige_relatorio_sla", "certidoes_exigidas", "responsaveis", "cor"]
        widgets = {"certidoes_exigidas": forms.CheckboxSelectMultiple, "responsaveis": forms.CheckboxSelectMultiple,
                   "cor": forms.TextInput(attrs={"type": "color"})}

    def clean(self):
        d = super().clean()
        if d.get("vigencia_inicio") and d.get("vigencia_fim") and d["vigencia_fim"] < d["vigencia_inicio"]:
            self.add_error("vigencia_fim", "O fim da vigência deve ser posterior ao início.")
        return d


def contratos_visiveis(user, qs):
    """Operação (técnicos) só vê contratos em que está alocado (seção 12)."""
    if not user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        qs = qs.filter(responsaveis=user)
    return qs


class ContratoLista(ListaGenerica):
    def get_queryset(self):
        return contratos_visiveis(self.request.user, super().get_queryset())


class ContratoHub(DetalheGenerico):
    """Página do contrato como hub com abas (seção 4.5, item 1)."""

    def get_queryset(self):
        return contratos_visiveis(self.request.user, super().get_queryset())

    def get_template_names(self):
        return ["contratos/hub.html"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.object
        aba = self.request.GET.get("aba", "resumo")
        if aba not in dict(ABAS):
            aba = "resumo"
        alertas = services.alertas_contrato(c)
        ctx.update({"abas": ABAS, "aba": aba, "alertas": alertas,
                    "saldo_baixo": any(a["chave"] == "saldo" for a in alertas), "fim_proximo": c.dias_para_fim < 30})
        if aba == "resumo":
            ctx.update({
                "aditivos": c.aditivos.all(), "itens": c.itens.all(), "empenhos": c.empenhos.all(),
                "competencias": c.competencias.order_by("-ano_mes")[:18],
            })
        elif aba in PROVEDORES:
            template, extra = PROVEDORES[aba](self.request, c)
            ctx.update({"aba_template": template, **extra})
        elif aba not in ("historico", "documentos"):
            ctx["aba_vazia"] = True
        return ctx


CRUD_CONTRATO = Crud(
    model=Contrato, prefixo="contrato", namespace="contratos", caminho="",
    subtitulo="Cada contrato é um centro de custo e de resultado.",
    colunas=[Coluna("Número", "numero", "mono", link=True), Coluna("Cliente", "cliente"),
             Coluna("Modalidade", "modalidade"), Coluna("Fim da vigência", "vigencia_fim", "data"),
             Coluna("Valor global", "valor_global", "brl"), Coluna("Status", "status", "status", "Contrato")],
    form_class=ContratoForm, busca=["numero", "objeto", "cliente__razao_social"],
    filtros=["status", "modalidade"], ordenacao=["-vigencia_inicio"], select_related=["cliente"],
    papeis_escrita=["Financeiro", "Fiscal"],
)


def _crud_filho(model, prefixo, colunas, fields, feminino=False, titulo=""):
    return Crud(model=model, prefixo=prefixo, namespace="contratos", colunas=colunas, fields=fields,
                feminino=feminino, titulo=titulo, select_related=["contrato"], papeis_escrita=["Financeiro", "Fiscal"],
                template_form="contratos/form_filho.html")


CRUD_ADITIVO = _crud_filho(
    Aditivo, "aditivo",
    [Coluna("Número", "numero", link=True), Coluna("Contrato", "contrato"), Coluna("Tipo", "tipo"),
     Coluna("Data", "data", "data"), Coluna("Acréscimo", "valor_acrescimo", "brl")],
    ["contrato", "numero", "tipo", "data", "nova_vigencia_fim", "valor_acrescimo", "percentual", "justificativa"])
CRUD_ITEM = _crud_filho(
    ItemContrato, "item",
    [Coluna("Descrição", "descricao", link=True), Coluna("Contrato", "contrato"), Coluna("Qtd.", "quantidade"),
     Coluna("Unitário", "valor_unitario", "brl"), Coluna("Total", "valor_total", "brl")],
    ["contrato", "descricao", "unidade", "quantidade", "valor_unitario"], titulo="Item do contrato")
CRUD_EMPENHO = _crud_filho(
    Empenho, "empenho",
    [Coluna("Número", "numero", "mono", link=True), Coluna("Contrato", "contrato"), Coluna("Data", "data", "data"),
     Coluna("Valor", "valor", "brl"), Coluna("Saldo", "saldo", "brl")],
    ["contrato", "numero", "data", "valor", "dotacao_orcamentaria", "fonte_recurso"])
CRUD_COMPETENCIA = Crud(
    model=Competencia, prefixo="competencia", namespace="contratos", feminino=True,
    colunas=[Coluna("Competência", "ano_mes", "competencia", link=True), Coluna("Contrato", "contrato"),
             Coluna("Status", "status", "status", "Competencia")],
    fields=["status"], filtros=["status"], ordenacao=["-ano_mes"], select_related=["contrato"],
    permitir_criar=False, papeis_escrita=["Financeiro", "Fiscal"],
)


@login_required
@require_POST
def gerar_competencias(request, pk):
    exigir_escrita(request.user, ["Financeiro", "Fiscal"])
    c = get_object_or_404(Contrato, pk=pk, empresa=request.empresa)
    n = services.gerar_competencias(c)
    messages.success(request, f"{n} competência(s) criada(s).")
    return redirect(reverse("contratos:contrato_detalhe", args=[pk]))
