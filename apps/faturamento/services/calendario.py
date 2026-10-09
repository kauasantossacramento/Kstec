"""Datas da agenda: competência → emissão → vencimento. Funções puras, sem acesso ao banco."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from apps.contratos.models import somar_meses

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def dia_no_mes(mes: date, dia: int) -> date:
    return mes.replace(day=min(dia, monthrange(mes.year, mes.month)[1]))


def proximo_dia_util(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def mes_emissao(agenda, competencia: date) -> date:
    return somar_meses(competencia, 1) if agenda.referencia == "MES_ANTERIOR" else competencia.replace(day=1)


def data_emissao(agenda, competencia: date) -> date:
    d = dia_no_mes(mes_emissao(agenda, competencia), agenda.dia_emissao)
    return proximo_dia_util(d) if agenda.dia_util else d


def data_vencimento(agenda, emissao: date) -> date:
    if agenda.tipo_vencimento == "DIA_FIXO" and agenda.dia_vencimento:
        mes = emissao.replace(day=1)
        alvo = dia_no_mes(mes, agenda.dia_vencimento)
        if alvo <= emissao:
            alvo = dia_no_mes(somar_meses(mes, 1), agenda.dia_vencimento)
        return alvo
    return emissao + timedelta(days=agenda.prazo_dias)


def mes_extenso(competencia: date) -> str:
    return f"{MESES[competencia.month - 1]}/{competencia.year}"


@dataclass
class Previsto:
    competencia: date
    emissao: date
    vencimento: date


def competencias(agenda, ate_emissao: date | None = None, limite: int = 120):
    """Competências da agenda em ordem, opcionalmente até uma data de emissão."""
    atual = agenda.inicio.replace(day=1)
    fim = agenda.fim_efetivo.replace(day=1)
    n = 0
    while atual <= fim and n < limite:
        emissao = data_emissao(agenda, atual)
        if ate_emissao and emissao > ate_emissao:
            break
        yield Previsto(atual, emissao, data_vencimento(agenda, emissao))
        atual = somar_meses(atual, 1)
        n += 1


def simular(agenda, quantidade=6, a_partir: date | None = None):
    """Prévia das próximas emissões (usada no wizard antes de salvar)."""
    desde = a_partir or date.today()
    return [p for p in competencias(agenda) if p.emissao >= desde][:quantidade]


def parcela(contrato, competencia: date):
    """Mês de execução contratual: o 1º mês é o seguinte ao do início da vigência (assinatura/publicação).
    Retorna (parcela, total). Ex.: assinado em 27/05 → junho = 01 de 12."""
    primeiro = somar_meses(contrato.vigencia_inicio.replace(day=1), 1)
    fim = contrato.vigencia_fim_atual.replace(day=1)
    meses = (competencia.year - primeiro.year) * 12 + competencia.month - primeiro.month + 1
    total = (fim.year - primeiro.year) * 12 + fim.month - primeiro.month + 1
    return meses, max(total, 1)
