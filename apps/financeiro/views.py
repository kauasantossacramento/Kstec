from datetime import timedelta
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.crud import Coluna, CriarGenerico, Crud, DetalheGenerico, EditarGenerico
from apps.core.permissoes import exigir_escrita

from .forms import BaixaForm, CategoriaForm, ExtratoForm, LancamentoForm, RecorrenciaForm
from .models import CategoriaFinanceira, CentroCusto, ContaBancaria, Lancamento, Recorrencia, TransacaoExtrato
from .services import lancamentos, relatorios

PAPEIS = ["Financeiro", "Fiscal"]

recorrencias = Crud(Recorrencia, "recorrencia", "financeiro", [Coluna("Descrição", "descricao", link=True),
    Coluna("Frequência", "frequencia"), Coluna("Valor", "valor", "brl"), Coluna("Ativa", "ativo", "bool")],
    feminino=True, caminho="recorrencias", form_class=RecorrenciaForm, papeis_escrita=["Financeiro"],
    papeis_leitura=PAPEIS, template_detalhe="financeiro/recorrencia.html")

contas = Crud(ContaBancaria, "conta", "financeiro", [Coluna("Nome", "nome", link=True),
    Coluna("Banco", "banco_codigo"), Coluna("Saldo inicial", "saldo_inicial", "brl")], caminho="contas",
    feminino=True, papeis_escrita=["Financeiro"], papeis_leitura=PAPEIS)
categorias = Crud(CategoriaFinanceira, "categoria", "financeiro", [Coluna("Nome", "nome", link=True),
    Coluna("Tipo", "tipo"), Coluna("Grupo", "grupo_dre")], caminho="categorias", feminino=True,
    form_class=CategoriaForm, papeis_escrita=["Financeiro"], papeis_leitura=PAPEIS)
centros = Crud(CentroCusto, "centro", "financeiro", [Coluna("Nome", "nome", link=True), Coluna("Contrato", "contrato")],
    caminho="centros", fields=["nome", "ratear", "ativo"], papeis_escrita=["Financeiro"], papeis_leitura=PAPEIS)
crud = Crud(Lancamento, "lancamento", "financeiro", [Coluna("Descrição", "descricao", link=True),
    Coluna("Tipo", "tipo"), Coluna("Vencimento", "data_vencimento", "data"),
    Coluna("Valor", "valor", "brl"), Coluna("Situação", "status", "status", entidade="Lancamento")],
    caminho="lancamentos", form_class=LancamentoForm, papeis_escrita=["Financeiro"], papeis_leitura=PAPEIS,
    busca=["descricao", "pessoa__razao_social"], filtros=["tipo", "status"],
    select_related=["categoria", "conta_bancaria", "centro_custo"],
    template_detalhe="financeiro/detalhe.html", campos_detalhe=LancamentoForm.Meta.fields + [
        "status", "data_pagamento", "valor_pago", "forma_pagamento", "juros", "multa", "desconto", "ordem_bancaria", "data_liquidacao",
    ])


class Persistir:
    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.empresa = self.request.empresa
        try:
            self.object = lancamentos.salvar(obj)
        except ValidationError as erro:
            form.add_error(None, erro)
            return self.form_invalid(form)
        messages.success(self.request, "Lançamento salvo.")
        return HttpResponseRedirect(self.get_success_url())


class CriarLancamento(Persistir, CriarGenerico):
    pass


class EditarLancamento(Persistir, EditarGenerico):
    pass


class DetalheLancamento(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.object.status in ("PAGO", "CANCELADO") or self.object.nota_fiscal_id:
            ctx["url_editar"] = None
        ctx["baixavel"] = self.object.status not in ("PAGO", "CANCELADO")
        return ctx


def _leitura(request):
    if not request.user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        raise PermissionDenied


@login_required
def home(request):
    _leitura(request)
    hoje = timezone.localdate()
    ctx = {"saldos": relatorios.saldos_contas(request.empresa, hoje), "aging": relatorios.aging(request.empresa, hoje),
           "fluxo": relatorios.fluxo_caixa(request.empresa, hoje, hoje + timedelta(days=90)),
           "vencidos": Lancamento.objects.filter(empresa=request.empresa).exclude(status__in=["PAGO", "CANCELADO"])
                .filter(data_vencimento__lt=hoje).order_by("data_vencimento")[:20]}
    return render(request, "financeiro/home.html", ctx)


@login_required
def baixar(request, pk):
    exigir_escrita(request.user, ["Financeiro"])
    obj = get_object_or_404(Lancamento, pk=pk, empresa=request.empresa)
    form = BaixaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            lancamentos.baixar(obj, **form.cleaned_data)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Baixa registrada. Nenhuma transação bancária foi executada.")
            return redirect("financeiro:lancamento_detalhe", pk=pk)
    return render(request, "financeiro/baixa.html", {"obj": obj, "form": form})


@login_required
@require_POST
def cancelar(request, pk):
    exigir_escrita(request.user, ["Financeiro"])
    obj = get_object_or_404(Lancamento, pk=pk, empresa=request.empresa)
    try:
        lancamentos.cancelar(obj, request.POST.get("motivo", ""))
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
    else:
        messages.success(request, "Lançamento cancelado com registro de auditoria.")
    return redirect("financeiro:lancamento_detalhe", pk=pk)


@login_required
def extratos(request):
    _leitura(request)
    form = ExtratoForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        exigir_escrita(request.user, ["Financeiro"])
        if form.is_valid():
            from .services.conciliacao import importar_extrato

            arquivo = form.cleaned_data["arquivo"]
            try:
                novos, repetidos = importar_extrato(request.empresa, form.cleaned_data["conta"], arquivo.read(), arquivo.name)
            except ValidationError as erro:
                form.add_error(None, erro)
            else:
                messages.success(request, f"{novos} transações importadas; {repetidos} já cadastradas.")
                return redirect("financeiro:extratos")
    from django.core.paginator import Paginator

    transacoes = TransacaoExtrato.objects.filter(empresa=request.empresa).select_related("conta_bancaria", "lancamento")
    return render(request, "financeiro/extratos.html", {"form": form,
                  "pode_escrever": request.user.tem_papel("Administrador", "Financeiro"),
                  "transacoes": Paginator(transacoes, 30).get_page(request.GET.get("page"))})


@login_required
def conciliar(request, pk):
    exigir_escrita(request.user, ["Financeiro"])
    transacao = get_object_or_404(TransacaoExtrato, pk=pk, empresa=request.empresa)
    if request.method == "POST":
        try:
            lancamento_id = UUID(request.POST.get("lancamento", ""))
        except (ValueError, TypeError):
            return HttpResponse("Selecione um lançamento válido.", status=400)
        obj = get_object_or_404(Lancamento, pk=lancamento_id, empresa=request.empresa)
        from .services.conciliacao import conciliar as registrar

        try:
            registrar(transacao, obj)
        except ValidationError as erro:
            messages.error(request, "; ".join(erro.messages))
        else:
            messages.success(request, "Transação conciliada e baixa registrada.")
            return redirect("financeiro:extratos")
    from django.db.models import Q

    candidatos = Lancamento.objects.filter(empresa=request.empresa, conciliado=False,
        tipo="RECEITA" if transacao.valor > 0 else "DESPESA").exclude(status="CANCELADO")
    candidatos = candidatos.filter(Q(conta_bancaria=transacao.conta_bancaria) | Q(conta_bancaria__isnull=True))
    candidatos = candidatos.filter(Q(status="PAGO", valor_pago=abs(transacao.valor))
                                  | (~Q(status="PAGO") & Q(valor=abs(transacao.valor))))
    return render(request, "financeiro/conciliar.html", {"transacao": transacao, "candidatos": candidatos[:100]})


@login_required
@require_POST
def gerar_recorrencia(request, pk):
    exigir_escrita(request.user, ["Financeiro"])
    obj = get_object_or_404(Recorrencia, pk=pk, empresa=request.empresa)
    from .services.recorrencias import gerar

    try:
        total = gerar(obj)
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
    else:
        messages.success(request, f"{total} previsão(ões) criada(s) para os próximos 12 meses.")
    return redirect("financeiro:recorrencia_detalhe", pk=pk)


@login_required
def demonstrativo(request):
    _leitura(request)
    from datetime import date

    hoje = timezone.localdate()
    try:
        inicio = date.fromisoformat(request.GET.get("inicio") or hoje.replace(day=1).isoformat())
        fim = date.fromisoformat(request.GET.get("fim") or hoje.isoformat())
        contrato = None
        if request.GET.get("contrato"):
            from apps.contratos.models import Contrato

            contrato = get_object_or_404(Contrato, pk=request.GET["contrato"], empresa=request.empresa)
        dados = relatorios.dre(request.empresa, inicio, fim, contrato)
    except (ValueError, ValidationError):
        return HttpResponse("Informe período e contrato válidos.", status=400)
    from apps.contratos.models import Contrato

    ctx = {"inicio": inicio, "fim": fim, "dre": dados, "contrato": contrato,
           "contratos": Contrato.objects.filter(empresa=request.empresa),
           "fluxo": relatorios.fluxo_caixa(request.empresa, inicio, fim, contrato)}
    return render(request, "financeiro/demonstrativo.html", ctx)
