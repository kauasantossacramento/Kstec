"""Abas do hub do contrato. Cada app registra a sua; abas sem provedor mostram empty_state."""

ABAS = [
    ("resumo", "Resumo"), ("notas", "Notas"), ("financeiro", "Financeiro"), ("tarefas", "Tarefas"),
    ("relatorios", "Relatórios"), ("custos", "Custos"), ("sla", "Sistemas/SLA"), ("documentos", "Documentos"),
    ("historico", "Histórico"),
]
PROVEDORES = {}


def aba(slug):
    def deco(fn):
        PROVEDORES[slug] = fn
        return fn
    return deco
