"""Previsão diária de recebimentos de um mês.

Fontes, sem duplicar a mesma receita:
1. RECEBIDO   — receitas pagas no mês (data do pagamento);
2. EM_ABERTO  — receitas lançadas (notas avulsas, recebíveis de NFS-e, lançamentos manuais) pelo vencimento;
3. PROGRAMADO — ciclos de faturamento ainda sem recebível, pelo vencimento previsto;
4. ESTIMADO   — competências futuras de agendas e contratos mensais sem agenda, pelo prazo contratual.
Ajustes mensais por contrato alteram data/valor ou excluem itens 2–4 apenas na previsão.
"""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.contratos.models import Contrato, somar_meses
from apps.financeiro.models import Lancamento
from apps.fiscal.models import NotaFiscal

from ..models import AgendaFaturamento, AjustePrevisao, CicloFaturamento
from . import calendario

ZERO = Decimal("0")
ORIGENS = {"RECEBIDO": ("Recebido", "success"), "EM_ABERTO": ("Lançado", "info"),
           "PROGRAMADO": ("Programado", "warning"), "ESTIMADO": ("Estimado", "neutral")}


@dataclass
class Item:
    data: date
    valor: Decimal
    titulo: str
    origem: str
    link: str = ""
    contrato: Contrato | None = None
    cliente: str = ""
    atrasado: bool = False
    excluido: bool = False
    ajuste: AjustePrevisao | None = None
    original: list = field(default_factory=list)

    @property
    def rotulo_origem(self):
        return ORIGENS[self.origem][0]

    @property
    def cor(self):
        return ORIGENS[self.origem][1]

    @property
    def ajustavel(self):
        return self.contrato is not None and self.origem != "RECEBIDO"


def ultimo_dia(mes):
    return mes.replace(day=monthrange(mes.year, mes.month)[1])


def _lancamentos(empresa, inicio, fim, hoje):
    itens = []
    base = Lancamento.objects.filter(empresa=empresa, tipo="RECEITA").select_related(
        "pessoa", "centro_custo__contrato", "nota_fiscal")
    for lanc in base.filter(status="PAGO", data_pagamento__range=(inicio, fim)):
        itens.append(Item(lanc.data_pagamento, lanc.valor_pago or lanc.valor, lanc.descricao, "RECEBIDO",
                          reverse("financeiro:lancamento_detalhe", args=[lanc.pk]), lanc.centro_custo.contrato,
                          str(lanc.pessoa or "")))
    abertos = base.filter(status__in=["PREVISTO", "PENDENTE", "ATRASADO"], data_vencimento__range=(inicio, fim))
    for lanc in abertos:
        itens.append(Item(lanc.data_vencimento, lanc.valor, lanc.descricao, "EM_ABERTO",
                          reverse("financeiro:lancamento_detalhe", args=[lanc.pk]), lanc.centro_custo.contrato,
                          str(lanc.pessoa or ""), atrasado=lanc.data_vencimento < hoje))
    return itens


def _ciclos(empresa, inicio, fim):
    itens = []
    com_recebivel = set(Lancamento.objects.filter(empresa=empresa, nota_fiscal__isnull=False)
                        .values_list("nota_fiscal_id", flat=True))
    qs = CicloFaturamento.objects.filter(empresa=empresa, data_vencimento__range=(inicio, fim)).exclude(
        status=CicloFaturamento.Status.PULADO).filter(
        Q(agenda__ativo=True, agenda__contrato__status=Contrato.Status.VIGENTE) | Q(nota__isnull=False)
    ).select_related("agenda__contrato__cliente")
    for c in qs:
        if c.nota_id and c.nota_id in com_recebivel:
            continue
        contrato = c.agenda.contrato
        itens.append(Item(c.data_vencimento, c.valor, f"{contrato.numero} · competência {c.competencia:%m/%Y}",
                          "PROGRAMADO", reverse("faturamento:ciclo", args=[c.pk]), contrato, str(contrato.cliente)))
    return itens


def _faturadas(empresa):
    """(contrato, competência) que já têm nota válida ou ciclo — não devem ser estimadas de novo."""
    notas = NotaFiscal.objects.filter(empresa=empresa, contrato__isnull=False).exclude(
        status__in=[NotaFiscal.Status.CANCELADA, NotaFiscal.Status.REJEITADA])
    feitas = {(n.contrato_id, n.competencia.replace(day=1)) for n in notas.only("contrato_id", "competencia")}
    feitas |= set(CicloFaturamento.objects.filter(empresa=empresa).values_list("agenda__contrato_id", "competencia"))
    return feitas


def _estimados(empresa, inicio, fim):
    itens = []
    feitas = _faturadas(empresa)
    agendas = AgendaFaturamento.objects.filter(empresa=empresa, ativo=True).select_related("contrato__cliente")
    com_agenda = set()
    for agenda in agendas:
        com_agenda.add(agenda.contrato_id)
        for p in calendario.competencias(agenda, ate_emissao=fim):
            if inicio <= p.vencimento <= fim and (agenda.contrato_id, p.competencia) not in feitas \
                    and p.emissao >= agenda.ativa_desde:
                c = agenda.contrato
                itens.append(Item(p.vencimento, agenda.valor, f"{c.numero} · competência {p.competencia:%m/%Y}",
                                  "ESTIMADO", reverse("faturamento:agenda", args=[agenda.pk]), c, str(c.cliente)))
    contratos = Contrato.objects.filter(empresa=empresa, status=Contrato.Status.VIGENTE,
                                        forma_faturamento=Contrato.Faturamento.MENSAL, valor_mensal__gt=0) \
        .exclude(pk__in=com_agenda).select_related("cliente")
    for c in contratos:
        comp = c.vigencia_inicio.replace(day=1)
        fim_vig = c.vigencia_fim_atual
        while comp <= fim_vig:
            emissao = calendario.dia_no_mes(somar_meses(comp, 1), c.dia_faturamento or 1)
            vencimento = emissao + timedelta(days=c.prazo_pagamento_dias)
            if vencimento > fim:
                break
            if vencimento >= inicio and (c.pk, comp) not in feitas:
                itens.append(Item(vencimento, c.valor_mensal, f"{c.numero} · competência {comp:%m/%Y}", "ESTIMADO",
                                  reverse("contratos:contrato_detalhe", args=[c.pk]), c, str(c.cliente)))
            comp = somar_meses(comp, 1)
    return itens


def _aplicar_ajustes(empresa, itens, inicio, fim):
    ajustes = {(a.contrato_id, a.mes): a for a in AjustePrevisao.objects.filter(
        empresa=empresa, ativo=True, mes__range=(inicio.replace(day=1), fim))}
    if not ajustes:
        return itens
    grupos, saida = {}, []
    for item in itens:
        chave = (item.contrato.pk if item.contrato else None, item.data.replace(day=1))
        if item.origem != "RECEBIDO" and chave in ajustes:
            grupos.setdefault(chave, []).append(item)
        else:
            saida.append(item)
    for chave, lista in grupos.items():
        ajuste = ajustes[chave]
        lista.sort(key=lambda i: i.data)
        base = lista[0]
        total = sum((i.valor for i in lista), ZERO)
        novo = Item(ajuste.data_prevista or base.data, total if ajuste.valor is None else ajuste.valor,
                    base.titulo if len(lista) == 1 else f"{base.contrato.numero} · {len(lista)} recebimentos",
                    base.origem, base.link, base.contrato, base.cliente, excluido=ajuste.excluir, ajuste=ajuste,
                    original=[(i.data, i.valor) for i in lista])
        novo.atrasado = not novo.excluido and novo.origem == "EM_ABERTO" and novo.data < timezone.localdate()
        saida.append(novo)
    return saida


def itens_periodo(empresa, inicio, fim, hoje=None):
    hoje = hoje or timezone.localdate()
    janela_ini, janela_fim = somar_meses(inicio.replace(day=1), -1), ultimo_dia(somar_meses(fim.replace(day=1), 1))
    brutos = _lancamentos(empresa, janela_ini, janela_fim, hoje) + _ciclos(empresa, janela_ini, janela_fim) \
        + _estimados(empresa, janela_ini, janela_fim)
    itens = _aplicar_ajustes(empresa, brutos, janela_ini, janela_fim)
    return sorted((i for i in itens if inicio <= i.data <= fim), key=lambda i: (i.data, i.origem, i.titulo))


def mes(empresa, referencia: date, hoje=None):
    hoje = hoje or timezone.localdate()
    inicio = referencia.replace(day=1)
    fim = ultimo_dia(inicio)
    itens = itens_periodo(empresa, inicio, fim, hoje)
    validos = [i for i in itens if not i.excluido]
    por_dia = {}
    for i in itens:
        por_dia.setdefault(i.data, []).append(i)
    totais = {o: sum((i.valor for i in validos if i.origem == o), ZERO) for o in ORIGENS}
    atrasados_anteriores = Lancamento.objects.filter(empresa=empresa, tipo="RECEITA",
        status__in=["PREVISTO", "PENDENTE", "ATRASADO"], data_vencimento__lt=min(inicio, hoje))
    # grade do calendário (segunda a domingo)
    grade_ini = inicio - timedelta(days=inicio.weekday())
    grade_fim = fim + timedelta(days=6 - fim.weekday())
    semanas, semana, d = [], [], grade_ini
    acumulado, serie_prevista, serie_recebida, rotulos = ZERO, [], [], []
    recebido_acum = ZERO
    while d <= grade_fim:
        do_dia = por_dia.get(d, [])
        total = sum((i.valor for i in do_dia if not i.excluido), ZERO)
        semana.append({"data": d, "itens": do_dia, "total": total, "fora": d.month != inicio.month, "hoje": d == hoje,
                       "origens": sorted({i.origem for i in do_dia if not i.excluido}),
                       "fim_semana": d.weekday() >= 5})
        if d.month == inicio.month:
            acumulado += total
            recebido_acum += sum((i.valor for i in do_dia if i.origem == "RECEBIDO"), ZERO)
            rotulos.append(d.day)
            serie_prevista.append(float(acumulado))
            serie_recebida.append(float(recebido_acum) if d <= hoje else None)
        if len(semana) == 7:
            semanas.append(semana)
            semana = []
        d += timedelta(days=1)
    melhor = max(((d, sum((i.valor for i in lista if not i.excluido), ZERO)) for d, lista in por_dia.items()),
                 key=lambda x: x[1], default=(None, ZERO))
    return {
        "inicio": inicio, "fim": fim, "anterior": somar_meses(inicio, -1), "proximo": somar_meses(inicio, 1),
        "itens": itens, "semanas": semanas, "totais": totais,
        "total": sum(totais.values(), ZERO), "a_receber": totais["EM_ABERTO"] + totais["PROGRAMADO"] + totais["ESTIMADO"],
        "atrasados_anteriores": atrasados_anteriores.count(),
        "valor_atrasados_anteriores": sum((lanc.valor for lanc in atrasados_anteriores), ZERO),
        "pico": melhor, "ajustes": [i for i in itens if i.ajuste],
        "grafico": {"type": "line", "moeda": True, "data": {"labels": rotulos, "datasets": [
            {"label": "Previsto acumulado", "data": serie_prevista, "fill": True, "tension": .25, "cor": "--primary"},
            {"label": "Recebido acumulado", "data": serie_recebida, "tension": .25, "cor": "--success"}]}},
    }


def contrato_no_mes(empresa, contrato, mes_ref):
    inicio = mes_ref.replace(day=1)
    return [i for i in itens_periodo(empresa, inicio, ultimo_dia(inicio))
            if i.contrato and i.contrato.pk == contrato.pk and i.origem != "RECEBIDO"]


def agenda_dias_semana(itens):
    """Resumo por dia para o bot do WhatsApp e relatórios."""
    por_dia = {}
    for i in itens:
        if not i.excluido:
            por_dia[i.data] = por_dia.get(i.data, ZERO) + i.valor
    return sorted(por_dia.items())


def abertos_ate(empresa, data):
    return Lancamento.objects.filter(empresa=empresa, tipo="RECEITA").filter(
        Q(status__in=["PREVISTO", "PENDENTE", "ATRASADO"]) & Q(data_vencimento__lte=data))
