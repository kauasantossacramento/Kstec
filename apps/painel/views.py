from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.core.agenda import eventos, itens_atencao

from . import indicadores


@login_required
def home(request):
    hoje = timezone.localdate()
    ctx = {
        "atencao": itens_atencao(request.empresa, request.user)[:12],
        "agenda": eventos(request.empresa, hoje, hoje + timedelta(days=15)),
        **indicadores.painel(request.empresa, request.user),
    }
    return render(request, "painel/home.html", ctx)


@login_required
def agenda(request):
    hoje = timezone.localdate()
    try:
        dias = max(7, min(int(request.GET.get("dias", 60)), 365))
    except ValueError:
        dias = 60
    lista = eventos(request.empresa, hoje - timedelta(days=7), hoje + timedelta(days=dias))
    tipos = sorted({e.tipo for e in lista})
    tipo = request.GET.get("tipo")
    if tipo:
        lista = [e for e in lista if e.tipo == tipo]
    return render(request, "painel/agenda.html", {"eventos": lista, "tipos": tipos, "tipo": tipo, "dias": dias,
                                                  "hoje": hoje})
