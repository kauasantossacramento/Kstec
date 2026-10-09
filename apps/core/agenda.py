"""Agenda de obrigações e lista "Precisa da sua atenção": cada app registra provedores.

Provedor de agenda: f(empresa, inicio, fim) -> list[Evento]
Provedor de atenção: f(empresa, usuario) -> list[ItemAtencao]
"""

from dataclasses import dataclass
from datetime import date

PROVEDORES_AGENDA = []
PROVEDORES_ATENCAO = []


@dataclass
class Evento:
    data: date
    titulo: str
    tipo: str  # CERTIDAO, CONTRATO, FISCAL, FINANCEIRO, SLA, RELATORIO, COMERCIAL
    link: str = ""
    nivel: str = "info"  # info | warning | danger | success
    detalhe: str = ""


@dataclass
class ItemAtencao:
    titulo: str
    link: str
    nivel: str = "warning"
    prioridade: int = 50  # menor = mais urgente
    detalhe: str = ""
    icone: str = "alert"


def agenda(fn):
    PROVEDORES_AGENDA.append(fn)
    return fn


def atencao(fn):
    PROVEDORES_ATENCAO.append(fn)
    return fn


def eventos(empresa, inicio, fim, usuario=None):
    saida = []
    for p in PROVEDORES_AGENDA:
        saida.extend(e for e in p(empresa, inicio, fim) if inicio <= e.data <= fim)
    if usuario is not None and not usuario.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        saida = [e for e in saida if e.tipo != "FINANCEIRO"]
    return sorted(saida, key=lambda e: (e.data, e.titulo))


def itens_atencao(empresa, usuario):
    saida = []
    for p in PROVEDORES_ATENCAO:
        saida.extend(p(empresa, usuario))
    return sorted(saida, key=lambda i: i.prioridade)
