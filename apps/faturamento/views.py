from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.contratos.models import Contrato
from apps.core.permissoes import exigir_escrita, pode_escrever

from .forms import AgendaForm, AjustePrevisaoForm, CicloForm, contratos_json
from .models import AgendaFaturamento, AjustePrevisao, CicloFaturamento
from .services import calendario, ciclos, previsao

S = CicloFaturamento.Status
LEITURA = ("Administrador", "Fiscal", "Financeiro", "Leitura")


def _leitura(request):
    if not request.user.tem_papel(*LEITURA):
        raise PermissionDenied


def _mensagem_erro(request, erro):
    messages.error(request, "; ".join(erro.messages))


@login_required
def home(request):
    _leitura(request)
    hoje = timezone.localdate()
    empresa = request.empresa
    qs = CicloFaturamento.objects.filter(empresa=empresa).select_related("agenda__contrato__cliente", "nota")
    mes_ini = hoje.replace(day=1)
    mes_fim = previsao.ultimo_dia(mes_ini)
    do_mes = qs.filter(data_emissao__range=(mes_ini, mes_fim)).exclude(status=S.PULADO).filter(
        Q(agenda__ativo=True) | Q(status__in=[S.AUTORIZADO, S.TRANSMITIDO]))
    agendas = AgendaFaturamento.objects.filter(empresa=empresa).select_related("contrato__cliente", "item_catalogo") \
        .annotate(autorizados=Count("ciclos", filter=Q(ciclos__status=S.AUTORIZADO)))
    linhas = [{"agenda": a, "proxima": ciclos.proxima_execucao(a) if a.ativo else None} for a in agendas]
    proximas = qs.filter(data_emissao__range=(hoje, hoje + timedelta(days=45)),
                         status__in=[S.PROGRAMADO, S.AGUARDANDO, S.BLOQUEADO], agenda__ativo=True)[:12]
    sem_agenda = Contrato.objects.filter(empresa=empresa, status=Contrato.Status.VIGENTE,
                                         forma_faturamento=Contrato.Faturamento.MENSAL,
                                         agenda_faturamento__isnull=True).count()
    from django.conf import settings

    return render(request, "faturamento/home.html", {
        "kpi_mes": do_mes.aggregate(v=Sum("valor"))["v"] or 0,
        "kpi_emitidas": do_mes.filter(status=S.AUTORIZADO).count(), "kpi_total_mes": do_mes.count(),
        "aguardando": qs.filter(status=S.AGUARDANDO, agenda__ativo=True).order_by("data_emissao"),
        "problemas": qs.filter(status__in=[S.BLOQUEADO, S.FALHA], agenda__ativo=True).order_by("data_emissao"),
        "rascunhos": qs.filter(status=S.RASCUNHO, agenda__ativo=True), "transmitidos": qs.filter(status=S.TRANSMITIDO),
        "proximas": proximas, "linhas": linhas, "sem_agenda": sem_agenda, "hoje": hoje,
        "pode_escrever": pode_escrever(request.user, ["Fiscal", "Financeiro"]),
        "pode_transmitir": pode_escrever(request.user, ["Fiscal"]),
        "automacao_eager": getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False),
    })


@login_required
@require_POST
def rodar_rotina(request):
    """Executa planejamento, emissões vencidas e consultas — útil no perfil local sem beat."""
    exigir_escrita(request.user, ["Fiscal"])
    planejados = ciclos.planejar_todas()
    processados = ciclos.processar()
    consultados = ciclos.acompanhar()
    messages.success(request, f"Rotina executada: {planejados} ciclo(s) planejado(s), {processados} processado(s), "
                              f"{consultados} consulta(s) de resultado.")
    return redirect("faturamento:home")


def _form_agenda(request, agenda=None):
    exigir_escrita(request.user, ["Fiscal", "Financeiro"])
    inicial = {}
    if agenda is None and request.GET.get("contrato"):
        inicial["contrato"] = request.GET["contrato"]
    form = AgendaForm(request.POST or None, instance=agenda, initial=inicial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.empresa = request.empresa
        if obj.contrato.empresa_id != request.empresa.pk:
            raise PermissionDenied
        obj.save()
        try:
            n = ciclos.planejar(obj)
        except ValidationError as erro:
            _mensagem_erro(request, erro)
            n = 0
        messages.success(request, ("Agenda criada" if agenda is None else "Agenda atualizada")
                         + f". {n} emissão(ões) programada(s) nos próximos 60 dias.")
        return redirect("faturamento:agenda", pk=obj.pk)
    pedido = request.GET.get("passo", "1")
    passo_padrao = int(pedido) if pedido.isdigit() and 1 <= int(pedido) <= 4 else 1
    passo_erro = next((p["numero"] for p in form.passos() if p["erros"]), passo_padrao if not form.non_field_errors() else 4)
    return render(request, "faturamento/agenda_form.html", {
        "form": form, "agenda": agenda, "contratos": contratos_json(request.empresa), "passo_inicial": passo_erro})


@login_required
def agenda_nova(request):
    return _form_agenda(request)


@login_required
def agenda_editar(request, pk):
    return _form_agenda(request, get_object_or_404(AgendaFaturamento, pk=pk, empresa=request.empresa))


@login_required
@require_POST
def simular(request):
    """Prévia (HTMX) das próximas emissões com os dados ainda não salvos do wizard."""
    _leitura(request)
    existente = AgendaFaturamento.objects.filter(pk=request.POST.get("agenda_pk") or None, empresa=request.empresa).first()         if request.POST.get("agenda_pk") else None
    form = AgendaForm(request.POST, instance=existente)
    form.is_valid()
    dados = form.cleaned_data
    contrato = dados.get("contrato")
    obrigatorios = ("inicio", "dia_emissao", "referencia", "tipo_vencimento")
    if not contrato or any(dados.get(c) in (None, "") for c in obrigatorios):
        return render(request, "faturamento/_simulacao.html", {"incompleto": True})
    agenda = AgendaFaturamento(contrato=contrato, **{k: v for k, v in dados.items()
                               if k in {f.name for f in AgendaFaturamento._meta.fields} and k != "contrato"})
    agenda.ativa_desde = timezone.localdate()
    if agenda.prazo_dias is None:
        agenda.prazo_dias = 0
    previstos = calendario.simular(agenda, 6, agenda.ativa_desde)
    texto = ""
    if previstos:
        ciclo = CicloFaturamento(agenda=agenda, competencia=previstos[0].competencia, valor=dados.get("valor") or 0)
        try:
            texto = ciclos.discriminacao(ciclo)
        except ValidationError as erro:
            texto = "; ".join(erro.messages)
    return render(request, "faturamento/_simulacao.html", {"previstos": previstos, "agenda": agenda,
                                                           "texto": texto, "valor": dados.get("valor")})


@login_required
def agenda(request, pk):
    _leitura(request)
    obj = get_object_or_404(AgendaFaturamento.objects.select_related("contrato__cliente", "item_catalogo", "perfil"),
                            pk=pk, empresa=request.empresa)
    lista = obj.ciclos.select_related("nota").order_by("-competencia")
    futuros = [p for p in calendario.simular(obj, 6, max(timezone.localdate(), obj.ativa_desde))
               if not obj.ciclos.filter(competencia=p.competencia).exists()]
    return render(request, "faturamento/agenda_detalhe.html", {
        "obj": obj, "ciclos": lista, "futuros": futuros, "proxima": ciclos.proxima_execucao(obj) if obj.ativo else None,
        "totais": lista.filter(status=S.AUTORIZADO).aggregate(v=Sum("valor"), n=Count("pk")),
        "pode_escrever": pode_escrever(request.user, ["Fiscal", "Financeiro"])})


@login_required
@require_POST
def agenda_ativar(request, pk):
    exigir_escrita(request.user, ["Fiscal", "Financeiro"])
    obj = get_object_or_404(AgendaFaturamento, pk=pk, empresa=request.empresa)
    obj.ativo = not obj.ativo
    if obj.ativo:
        obj.ativa_desde = max(obj.ativa_desde, timezone.localdate()) if obj.ativa_desde else timezone.localdate()
    obj.save()
    if obj.ativo:
        ciclos.planejar(obj)
    messages.success(request, "Agenda retomada." if obj.ativo else "Agenda pausada. Nenhuma emissão será feita.")
    return redirect("faturamento:agenda", pk=pk)


def eventos_legiveis(eventos):
    from datetime import datetime

    saida = []
    for e in reversed(eventos):
        try:
            quando = timezone.localtime(datetime.fromisoformat(e["em"]))
        except (KeyError, ValueError):
            quando = None
        saida.append({**e, "em": quando})
    return saida


def _ciclo(request, pk):
    return get_object_or_404(CicloFaturamento.objects.select_related("agenda__contrato__cliente", "nota"),
                             pk=pk, empresa=request.empresa)


@login_required
def ciclo(request, pk):
    _leitura(request)
    obj = _ciclo(request, pk)
    form = CicloForm(instance=obj) if obj.status in CicloFaturamento.EDITAVEIS and not obj.nota_id else None
    texto = ""
    try:
        texto = ciclos.discriminacao(obj)
    except ValidationError as erro:
        texto = "; ".join(erro.messages)
    return render(request, "faturamento/ciclo_detalhe.html", {
        "obj": obj, "form": form, "texto": texto, "eventos": eventos_legiveis(obj.eventos),
        "pode_escrever": pode_escrever(request.user, ["Fiscal", "Financeiro"]),
        "pode_transmitir": pode_escrever(request.user, ["Fiscal"])})


@login_required
@require_POST
def ciclo_acao(request, pk, acao):
    obj = _ciclo(request, pk)
    papeis = ["Fiscal"] if acao in ("executar", "confirmar") else ["Fiscal", "Financeiro"]
    exigir_escrita(request.user, papeis)
    try:
        if acao == "executar":
            obj = ciclos.executar(obj, request.user, manual=True)
            messages.success(request, obj.mensagem or "Ciclo processado.")
        elif acao == "confirmar":
            obj = ciclos.confirmar(obj, request.user)
            messages.success(request, obj.mensagem or "Transmissão confirmada.")
        elif acao == "pular":
            ciclos.pular(obj, request.POST.get("motivo", ""), request.user)
            messages.success(request, "Competência marcada como não faturada.")
        elif acao == "retomar":
            ciclos.retomar(obj, request.user)
            messages.success(request, "Ciclo devolvido à fila de emissão.")
        elif acao == "refazer":
            ciclos.refazer(obj, request.user)
            messages.success(request, "Nova nota será gerada na próxima execução.")
        elif acao == "ajustar":
            form = CicloForm(request.POST, instance=CicloFaturamento.objects.get(pk=obj.pk))
            if not form.is_valid():
                messages.error(request, "Revise os campos do ajuste: " + "; ".join(
                    f"{form.fields[c].label}: {' '.join(e)}" if c in form.fields else " ".join(e)
                    for c, e in form.errors.items()))
            else:
                d = form.cleaned_data
                ciclos.ajustar(obj, valor=d["valor"], data_emissao=d["data_emissao"],
                               data_vencimento=d["data_vencimento"], discriminacao_texto=d["discriminacao"],
                               usuario=request.user)
                messages.success(request, "Ajuste aplicado somente a esta competência.")
        else:
            raise Http404
    except ValidationError as erro:
        _mensagem_erro(request, erro)
    destino = request.POST.get("_proximo")
    if destino and destino.startswith("/"):
        return redirect(destino)
    return redirect("faturamento:ciclo", pk=pk)


# ---------------------------------------------------------------------------
# Previsão de recebimentos
# ---------------------------------------------------------------------------

def _mes(valor):
    try:
        return date.fromisoformat(f"{valor}-01") if valor else timezone.localdate().replace(day=1)
    except ValueError:
        raise Http404


@login_required
def recebimentos(request):
    _leitura(request)
    referencia = _mes(request.GET.get("mes"))
    dados = previsao.mes(request.empresa, referencia)
    dia = request.GET.get("dia")
    selecionado = None
    if dia:
        try:
            selecionado = date.fromisoformat(dia)
        except ValueError:
            selecionado = None
    return render(request, "faturamento/recebimentos.html", {
        **dados, "selecionado": selecionado, "origens": previsao.ORIGENS,
        "itens_dia": [i for i in dados["itens"] if i.data == selecionado] if selecionado else None,
        "pode_ajustar": pode_escrever(request.user, ["Financeiro"])})


@login_required
def ajustar_previsao(request, contrato_pk, mes):
    exigir_escrita(request.user, ["Financeiro"])
    contrato = get_object_or_404(Contrato, pk=contrato_pk, empresa=request.empresa)
    referencia = _mes(mes)
    ajuste = AjustePrevisao.objects.filter(contrato=contrato, mes=referencia).first()
    form = AjustePrevisaoForm(request.POST or None, instance=ajuste, mes=referencia)
    if request.method == "POST":
        if request.POST.get("remover") and ajuste:
            ajuste.delete()
            messages.success(request, "Ajuste removido. A previsão voltou ao cálculo automático.")
            return redirect(f"{_url_mes(referencia)}")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.empresa, obj.contrato, obj.mes = request.empresa, contrato, referencia
            obj.save()
            messages.success(request, f"Previsão de {contrato.numero} ajustada para {referencia:%m/%Y}.")
            return redirect(f"{_url_mes(referencia)}")
    originais = previsao.contrato_no_mes(request.empresa, contrato, referencia)
    return render(request, "faturamento/ajuste_form.html", {"form": form, "contrato": contrato, "mes": referencia,
                                                            "ajuste": ajuste, "originais": originais})


def _url_mes(referencia):
    from django.urls import reverse

    return reverse("faturamento:recebimentos") + f"?mes={referencia:%Y-%m}"
