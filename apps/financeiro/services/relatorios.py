"""Relatórios gerenciais por competência e fluxo de caixa por pagamento."""

from decimal import Decimal

from django.db.models import Sum

from ..models import ContaBancaria, Lancamento

ZERO = Decimal("0.00")


def _periodo(inicio, fim):
    from django.core.exceptions import ValidationError

    if fim < inicio:
        raise ValidationError("O fim do período deve ser igual ou posterior ao início.")


def base(empresa, contrato=None):
    qs = Lancamento.objects.filter(empresa=empresa).exclude(status="CANCELADO")
    if contrato:
        qs = qs.filter(centro_custo__contrato=contrato)
    return qs


def dre(empresa, inicio, fim, contrato=None):
    _periodo(inicio, fim)
    qs = base(empresa, contrato).filter(data_competencia__range=(inicio, fim))
    grupos = {g: ZERO for g in ("RECEITA_BRUTA", "DEDUCOES", "CUSTO_SERVICO", "DESPESA_OPERACIONAL",
                                  "DESPESA_FINANCEIRA", "IMPOSTOS", "INVESTIMENTO", "NAO_OPERACIONAL")}
    for linha in qs.values("categoria__grupo_dre", "tipo").annotate(total=Sum("valor")):
        grupo = linha["categoria__grupo_dre"]
        sinal = -1 if grupo == "NAO_OPERACIONAL" and linha["tipo"] == "DESPESA" else 1
        grupos[grupo] += sinal * linha["total"]
    receita = grupos["RECEITA_BRUTA"]
    deducoes = grupos["DEDUCOES"] + grupos["IMPOSTOS"]
    liquida = receita - deducoes
    margem = liquida - grupos["CUSTO_SERVICO"]
    despesas = grupos["DESPESA_OPERACIONAL"] + grupos["DESPESA_FINANCEIRA"]
    return {"receita_bruta": receita, "deducoes": deducoes, "receita_liquida": liquida,
            "custos": grupos["CUSTO_SERVICO"], "margem_contribuicao": margem,
            "despesas": despesas, "nao_operacional": grupos["NAO_OPERACIONAL"],
            "resultado": margem - despesas + grupos["NAO_OPERACIONAL"], "investimentos": grupos["INVESTIMENTO"]}


def fluxo_caixa(empresa, inicio, fim, contrato=None):
    _periodo(inicio, fim)
    qs = base(empresa, contrato)
    pagos = qs.filter(status="PAGO", data_pagamento__range=(inicio, fim))
    previstos = qs.exclude(status="PAGO").filter(data_vencimento__range=(inicio, fim))
    def total(query, tipo, campo):
        return query.filter(tipo=tipo).aggregate(v=Sum(campo))["v"] or ZERO
    return {"entradas": total(pagos, "RECEITA", "valor_pago"), "saidas": total(pagos, "DESPESA", "valor_pago"),
            "entradas_previstas": total(previstos, "RECEITA", "valor"), "saidas_previstas": total(previstos, "DESPESA", "valor")}


def saldos_contas(empresa, data):
    contas = []
    for conta in ContaBancaria.objects.filter(empresa=empresa, ativo=True, data_saldo_inicial__lte=data):
        qs = conta.lancamentos.filter(status="PAGO", data_pagamento__range=(conta.data_saldo_inicial, data))
        entrada = qs.filter(tipo="RECEITA").aggregate(v=Sum("valor_pago"))["v"] or ZERO
        saida = qs.filter(tipo="DESPESA").aggregate(v=Sum("valor_pago"))["v"] or ZERO
        contas.append({"conta": conta, "saldo": conta.saldo_inicial + entrada - saida})
    return contas


def aging(empresa, hoje):
    from datetime import timedelta

    qs = base(empresa).filter(tipo="RECEITA").exclude(status="PAGO")
    faixas = []
    for nome, minimo, maximo in [("A vencer / vence hoje", None, 0), ("1 a 30 dias", 1, 30),
        ("31 a 60 dias", 31, 60), ("61 a 90 dias", 61, 90), ("Mais de 90 dias", 91, None)]:
        faixa = qs
        if minimo is not None:
            faixa = faixa.filter(data_vencimento__lte=hoje - timedelta(days=minimo))
        if maximo is not None:
            faixa = faixa.filter(data_vencimento__gte=hoje - timedelta(days=maximo))
        faixas.append({"nome": nome, "total": faixa.aggregate(v=Sum("valor"))["v"] or ZERO, "quantidade": faixa.count()})
    return faixas
