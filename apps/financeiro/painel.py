from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from apps.core.agenda import Evento, ItemAtencao, agenda, atencao
from apps.painel.indicadores import indicador

from .models import Lancamento


@indicador
def financeiro(empresa, usuario):
    if not usuario.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        return {}
    from .services.relatorios import dre

    hoje = timezone.localdate()
    pendentes = Lancamento.objects.filter(empresa=empresa, tipo="RECEITA").exclude(status__in=["PAGO", "CANCELADO"])
    return {"a_receber": pendentes.aggregate(v=Sum("valor"))["v"] or 0,
            "resultado_mes": dre(empresa, hoje.replace(day=1), hoje)["resultado"]}


@agenda
def vencimentos(empresa, inicio, fim):
    qs = Lancamento.objects.filter(empresa=empresa, data_vencimento__range=(inicio, fim)).exclude(status__in=["PAGO", "CANCELADO"])
    return [Evento(obj.data_vencimento, obj.descricao, "FINANCEIRO", reverse("financeiro:lancamento_detalhe", args=[obj.pk]),
                   "danger" if obj.vencido else "info", str(obj.valor)) for obj in qs]


@atencao
def atrasados(empresa, usuario):
    if not usuario.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        return []
    qs = Lancamento.objects.filter(empresa=empresa, data_vencimento__lt=timezone.localdate()).exclude(status__in=["PAGO", "CANCELADO"])
    quantidade = qs.count()
    if not quantidade:
        return []
    total = qs.aggregate(v=Sum("valor"))["v"]
    return [ItemAtencao(f"{quantidade} lançamento(s) vencido(s)", reverse("financeiro:home"), "danger", 20, str(total), "wallet")]
