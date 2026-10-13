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
    from .services import indicadores
    from .services.relatorios import dre

    hoje = timezone.localdate()
    abertos = indicadores.abertos(empresa)
    vencidos = abertos.filter(data_vencimento__lt=hoje)
    fat = indicadores.faturamento(empresa, hoje.replace(day=1))
    return {"a_receber": abertos.aggregate(v=Sum("valor"))["v"] or 0,
            "a_receber_vencido": vencidos.aggregate(v=Sum("valor"))["v"] or 0, "tem_vencido": vencidos.exists(),
            "faturado_mes": fat["total_competencia"], "emitido_mes": fat["total_emitidas"],
            "link_a_receber": reverse("financeiro:a_receber"), "link_faturado": reverse("financeiro:faturamento_mes"),
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
    from .services import indicadores

    qs = indicadores.abertos(empresa).filter(data_vencimento__lt=timezone.localdate())
    quantidade = qs.count()
    if not quantidade:
        return []
    total = qs.aggregate(v=Sum("valor"))["v"]
    return [ItemAtencao(f"{quantidade} recebível(is) vencido(s)", reverse("financeiro:a_receber") + "?situacao=vencidos",
                        "danger", 20, str(total), "wallet")]
