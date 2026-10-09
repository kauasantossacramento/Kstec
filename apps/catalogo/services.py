"""Preço do configurador gráfico, sugestão de códigos fiscais e importação das tabelas de referência."""

from decimal import ROUND_HALF_UP, Decimal

from .models import (
    CodigoNBS,
    CodigoTributacaoNacional,
    CorrelacaoNBS,
    FaixaPreco,
    ItemCatalogo,
    VariacaoGrafica,
)

D4 = Decimal("0.0001")
D2 = Decimal("0.01")


def preco_faixa(item: ItemCatalogo, quantidade: Decimal) -> Decimal:
    faixa = (FaixaPreco.objects.filter(item=item, quantidade_min__lte=quantidade)
             .order_by("-quantidade_min").first())
    if faixa and (faixa.quantidade_max is None or quantidade <= faixa.quantidade_max):
        return faixa.preco_unitario
    return item.preco_base


def calcular_preco(item: ItemCatalogo, quantidade, variacoes_ids=()) -> dict:
    """Preço unitário = (faixa + acréscimos por unidade) × (1 + Σ percentuais) + Σ fixos ÷ quantidade.

    Ex. (500 cartões): faixa 0,55 + couché 300g 0,05/un → 0,60; verniz +20% → 0,72;
    faca especial R$ 50 fixo ÷ 500 = 0,10 → unitário 0,82; total R$ 410,00.
    """
    qtd = Decimal(str(quantidade or 0))
    if qtd <= 0:
        return {"unitario": Decimal("0"), "total": Decimal("0"), "detalhes": []}
    base = preco_faixa(item, qtd)
    variacoes = list(VariacaoGrafica.objects.filter(item=item, pk__in=list(variacoes_ids or [])))
    detalhes = [{"rotulo": f"Preço da faixa ({qtd.normalize()} {item.get_unidade_display().lower()})", "valor": base}]
    por_unidade = sum((v.acrescimo_valor for v in variacoes if v.acrescimo_tipo == "POR_UNIDADE"), Decimal("0"))
    percentual = sum((v.acrescimo_valor for v in variacoes if v.acrescimo_tipo == "PERCENTUAL"), Decimal("0"))
    fixo = sum((v.acrescimo_valor for v in variacoes if v.acrescimo_tipo == "FIXO"), Decimal("0"))
    for v in variacoes:
        detalhes.append({"rotulo": str(v), "valor": v.acrescimo_valor, "tipo": v.acrescimo_tipo})
    unit = (base + por_unidade) * (1 + percentual / 100) + fixo / qtd
    unit = unit.quantize(D4, rounding=ROUND_HALF_UP)
    total = (unit * qtd).quantize(D2, rounding=ROUND_HALF_UP)
    return {"unitario": unit, "total": total, "detalhes": detalhes,
            "variacoes": [{"id": str(v.pk), "rotulo": str(v)} for v in variacoes]}


def sugestoes_fiscais(item_lc116: str) -> dict:
    """NBS correlatas (Anexo VIII) e cTribNac do item da LC 116 escolhido."""
    item_lc116 = (item_lc116 or "").strip()
    nbs_codigos = list(CorrelacaoNBS.objects.filter(item_lc116=item_lc116).values_list("nbs", flat=True).distinct())
    nbs = CodigoNBS.objects.filter(codigo__in=nbs_codigos)
    item, sub = (item_lc116.split(".") + [""])[:2]
    ctrib = CodigoTributacaoNacional.objects.filter(item=item, subitem=sub)
    return {
        "nbs": [{"id": str(n.pk), "rotulo": str(n)} for n in nbs],
        "codigo_tributacao_nacional": [{"id": str(c.pk), "rotulo": str(c)} for c in ctrib],
    }


def buscar_nbs(termo: str, limite=20):
    """Busca por texto ('hospedagem', 'suporte') em NBS e correlações."""
    from django.db.models import Q

    return CodigoNBS.objects.filter(Q(descricao__icontains=termo) | Q(codigo__startswith=termo))[:limite]
