"""Indicadores do painel. Cada app contribui por meio de funções registradas (ampliado nas fases seguintes)."""

PROVEDORES = []


def indicador(fn):
    PROVEDORES.append(fn)
    return fn


def painel(empresa, usuario) -> dict:
    ctx = {}
    for p in PROVEDORES:
        ctx.update(p(empresa, usuario) or {})
    return ctx
