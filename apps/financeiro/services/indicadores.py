"""Recebíveis e faturamento para os indicadores: o que compõe cada valor, com filtros por mês.

Regras de soma:
- a receber = receitas não pagas e não canceladas; quando o lançamento vem de NFS-e, a nota precisa estar autorizada
  (nota cancelada/rejeitada não é dinheiro a receber);
- faturado no mês = NFS-e autorizadas cuja COMPETÊNCIA é o mês (o serviço prestado no mês), separado do que foi
  EMITIDO no mês (que pode incluir competências atrasadas).
"""

from calendar import monthrange
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum

from ..models import Lancamento

ZERO = Decimal("0")
FAIXAS = [("a_vencer", "A vencer", None, 0), ("1_30", "Vencidos há 1–30 dias", 1, 30), ("31_60", "31–60 dias", 31, 60),
          ("61_90", "61–90 dias", 61, 90), ("90_mais", "Mais de 90 dias", 91, None)]


def mes_de(texto, padrao):
    try:
        return date.fromisoformat(f"{texto}-01") if texto else padrao.replace(day=1)
    except ValueError:
        return padrao.replace(day=1)


def fim_mes(mes):
    return mes.replace(day=monthrange(mes.year, mes.month)[1])


def abertos(empresa):
    """Receitas a receber de fato (ver regras no topo)."""
    return (Lancamento.objects.filter(empresa=empresa, tipo="RECEITA").exclude(status__in=["PAGO", "CANCELADO"])
            .filter(Q(nota_fiscal__isnull=True) | Q(nota_fiscal__status="AUTORIZADA"))
            .select_related("nota_fiscal__contrato", "pessoa", "centro_custo__contrato", "conta_bancaria"))


def contrato_de(lanc):
    nota = lanc.nota_fiscal
    if nota and nota.contrato_id:
        return nota.contrato
    return lanc.centro_custo.contrato if lanc.centro_custo_id else None


def competencia_de(lanc):
    nota = lanc.nota_fiscal
    return (nota.competencia if nota else lanc.data_competencia).replace(day=1)


def faixa_atraso(lanc, hoje):
    dias = (hoje - lanc.data_vencimento).days
    for chave, _nome, minimo, maximo in FAIXAS:
        if (minimo is None or dias >= minimo) and (maximo is None or dias <= maximo):
            return chave
    return "a_vencer"


def resumo(empresa, hoje, mes=None, base="vencimento", contrato=None, situacao=""):
    """Lista e totais dos recebíveis em aberto. `mes` filtra pelo mês de vencimento ou de competência (`base`)."""
    linhas = []
    for lanc in abertos(empresa).order_by("data_vencimento", "descricao"):
        c = contrato_de(lanc)
        comp = competencia_de(lanc)
        if contrato and (c is None or c.pk != contrato.pk):
            continue
        if mes:
            ref = comp if base == "competencia" else lanc.data_vencimento.replace(day=1)
            if ref != mes:
                continue
        vencido = lanc.data_vencimento < hoje
        if situacao == "vencidos" and not vencido or situacao == "a_vencer" and vencido:
            continue
        linhas.append({"obj": lanc, "contrato": c, "competencia": comp, "vencido": vencido,
                       "dias": (hoje - lanc.data_vencimento).days, "faixa": faixa_atraso(lanc, hoje)})
    total = sum((x["obj"].valor for x in linhas), ZERO)
    vencido = sum((x["obj"].valor for x in linhas if x["vencido"]), ZERO)
    faixas = [{"chave": k, "nome": n, "total": sum((x["obj"].valor for x in linhas if x["faixa"] == k), ZERO),
               "quantidade": sum(1 for x in linhas if x["faixa"] == k)} for k, n, _a, _b in FAIXAS]
    por_contrato = OrderedDict()
    for x in linhas:
        chave = x["contrato"].numero if x["contrato"] else "Sem contrato"
        g = por_contrato.setdefault(chave, {"contrato": x["contrato"], "total": ZERO, "vencido": ZERO, "quantidade": 0})
        g["total"] += x["obj"].valor
        g["vencido"] += x["obj"].valor if x["vencido"] else ZERO
        g["quantidade"] += 1
    por_mes = OrderedDict()
    for x in sorted(linhas, key=lambda y: y["obj"].data_vencimento):
        m = x["obj"].data_vencimento.replace(day=1)
        g = por_mes.setdefault(m, {"mes": m, "total": ZERO, "quantidade": 0})
        g["total"] += x["obj"].valor
        g["quantidade"] += 1
    maior = max([g["total"] for g in por_mes.values()] or [ZERO]) or Decimal(1)
    for g in por_mes.values():
        g["pct"] = int(g["total"] / maior * 100)
    return {"linhas": linhas, "total": total, "vencido": vencido, "a_vencer": total - vencido, "faixas": faixas,
            "por_contrato": sorted(por_contrato.values(), key=lambda g: -g["total"]), "por_mes": list(por_mes.values())}


def recebido(empresa, mes):
    qs = Lancamento.objects.filter(empresa=empresa, tipo="RECEITA", status="PAGO",
                                   data_pagamento__range=(mes, fim_mes(mes)))
    return {"total": qs.aggregate(v=Sum("valor_pago"))["v"] or ZERO, "quantidade": qs.count(), "lista": qs.order_by("data_pagamento")}


def faturamento(empresa, mes):
    """Notas autorizadas: por competência do mês e emitidas no mês (podem divergir quando há competências atrasadas)."""
    from apps.fiscal.models import NotaFiscal

    autorizadas = NotaFiscal.objects.filter(empresa=empresa, status="AUTORIZADA").select_related("contrato", "tomador")
    por_comp = list(autorizadas.filter(competencia__range=(mes, fim_mes(mes))).order_by("contrato__numero"))
    inicio = mes
    fim = fim_mes(mes) + timedelta(days=1)
    emitidas = list(autorizadas.filter(autorizada_em__date__gte=inicio, autorizada_em__date__lt=fim).order_by("competencia"))
    soma = lambda lista: sum((n.valor_servicos for n in lista), ZERO)  # noqa: E731
    return {"competencia": por_comp, "total_competencia": soma(por_comp), "emitidas": emitidas, "total_emitidas": soma(emitidas),
            "atrasadas": [n for n in emitidas if n.competencia < mes], "total_atrasadas": soma([n for n in emitidas if n.competencia < mes])}
