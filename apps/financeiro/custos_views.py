"""Tela de custos (menu Custos): relatório geral, por centro de custo e por contrato, com rateio dos custos globais."""

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils import timezone

from apps.contratos.models import somar_meses
from apps.core.permissoes import pode_escrever

from .models import CentroCusto
from .services import custos_relatorio as srv


def _periodo(request):
    hoje = timezone.localdate()
    try:
        inicio = date.fromisoformat(request.GET.get("inicio") or somar_meses(hoje.replace(day=1), -5).isoformat())
        fim = date.fromisoformat(request.GET.get("fim") or hoje.isoformat())
    except ValueError:
        inicio, fim = somar_meses(hoje.replace(day=1), -5), hoje
    return inicio, max(fim, inicio)


def _dados(request):
    if not request.user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        raise PermissionDenied
    inicio, fim = _periodo(request)
    contrato = srv.contratos_para_filtro(request.empresa).filter(pk=request.GET.get("contrato")).first() \
        if request.GET.get("contrato") else None
    return srv.apurar(request.empresa, inicio, fim, contrato)


@login_required
def relatorio(request):
    dados = _dados(request)
    return render(request, "financeiro/custos.html", {
        **dados, "contratos": srv.contratos_para_filtro(request.empresa),
        "globais": CentroCusto.objects.filter(empresa=request.empresa, contrato__isnull=True),
        "pode_escrever": pode_escrever(request.user, ["Financeiro"]), "querystring": request.GET.urlencode()})


@login_required
def exportar(request):
    dados = _dados(request)
    resposta = HttpResponse(srv.xlsx(dados), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resposta["Content-Disposition"] = f'attachment; filename="custos_{dados["inicio"]:%Y%m}_{dados["fim"]:%Y%m}.xlsx"'
    return resposta


app_name = "custos"
urlpatterns = [path("", relatorio, name="planilha_lista"), path("exportar/", exportar, name="exportar")]
