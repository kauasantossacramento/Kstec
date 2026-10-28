"""Alteração do valor mensal de um contrato a partir de uma competência (reajuste, correção, repactuação).

Competências anteriores à data mantêm o valor antigo (ficam personalizadas, para o planejamento não sincronizá-las);
as programadas a partir da data passam ao novo valor. Ciclos já em preparo, emitidos ou personalizados não são
alterados: aparecem na prévia para ajuste manual. O valor global do contrato não muda (formalize por aditivo).
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.templatetags.ks import brl

from ..models import AgendaFaturamento, CicloFaturamento
from . import ciclos

S = CicloFaturamento.Status
LIVRES = (S.PROGRAMADO, S.BLOQUEADO)


def _planejar_ate(agenda, a_partir):
    """Garante que existam os ciclos até a competência da alteração, para separar o antes e o depois."""
    hoje = timezone.localdate()
    alvo = max(hoje, a_partir) + timedelta(days=62)
    ciclos.planejar(agenda, hoje=hoje, horizonte_dias=(alvo - hoje).days)


def classificar(agenda, a_partir):
    """Ciclos afetados: 'manter' (antes da data, ainda livres), 'alterar' (a partir da data, livres) e
    'revisar' (a partir da data, mas em preparo, emitidos ou personalizados)."""
    _planejar_ate(agenda, a_partir)
    qs = CicloFaturamento.objects.filter(agenda=agenda).order_by("competencia")
    manter = [c for c in qs.filter(competencia__lt=a_partir, status__in=LIVRES, personalizado=False)
              if c.valor == agenda.valor]
    depois = list(qs.filter(competencia__gte=a_partir).exclude(status=S.PULADO))
    alterar = [c for c in depois if c.status in LIVRES and not c.personalizado]
    revisar = [c for c in depois if c not in alterar]
    return {"manter": manter, "alterar": alterar, "revisar": revisar}


def previa(agenda, novo, a_partir):
    if novo <= 0:
        raise ValidationError("O novo valor deve ser maior que zero.")
    if novo == agenda.valor:
        raise ValidationError(f"O contrato {agenda.contrato.numero} já está com {brl(novo)}.")
    grupos = classificar(agenda, a_partir.replace(day=1))
    contrato = agenda.contrato
    linhas = [f"📝 *Alterar valor* · {contrato.numero} — {contrato.cliente}",
              f"De {brl(agenda.valor)} para *{brl(novo)}* por mês, a partir da competência *{a_partir:%m/%Y}*."]
    if grupos["alterar"]:
        linhas.append("Passam ao novo valor: " + ", ".join(
            f"{c.competencia:%m/%Y} (emissão {c.data_emissao:%d/%m})" for c in grupos["alterar"][:6])
            + (" e as seguintes" if len(grupos["alterar"]) > 6 else "") + ".")
    if grupos["manter"]:
        linhas.append("Mantêm " + brl(agenda.valor) + ": " + ", ".join(f"{c.competencia:%m/%Y}" for c in grupos["manter"]) + ".")
    if grupos["revisar"]:
        linhas.append("⚠️ Não serão alterados (revise na tela): " + "; ".join(
            f"{c.competencia:%m/%Y} {c.get_status_display().lower()}"
            + (f" NFS-e {c.nota.numero_nfse}" if c.nota_id and c.nota.numero_nfse else "")
            + (" (valor personalizado)" if c.personalizado and c.status in LIVRES else "") + f" {brl(c.valor)}"
            for c in grupos["revisar"]) + ".")
    linhas.append("O valor global do contrato não muda; se for reajuste formal, registre o aditivo ou apostilamento.")
    return "\n".join(linhas)


@transaction.atomic
def aplicar(agenda, novo, a_partir, motivo, valor_anterior, por=""):
    agenda = AgendaFaturamento.objects.select_for_update().select_related("contrato").get(pk=agenda.pk)
    if agenda.valor != valor_anterior:
        raise ValidationError(f"O valor da agenda mudou para {brl(agenda.valor)} depois do pedido; peça novamente.")
    a_partir = a_partir.replace(day=1)
    grupos = classificar(agenda, a_partir)
    texto = (f"Valor alterado de {brl(valor_anterior)} para {brl(novo)} a partir da competência {a_partir:%m/%Y}"
             + (f" — {motivo}" if motivo else "") + (f" ({por})" if por else "") + ".")
    for c in grupos["manter"]:
        c.personalizado = True
        c.registrar("valor", f"Valor {brl(c.valor)} mantido: alteração vale a partir de {a_partir:%m/%Y}.", por)
        c.save()
    for c in grupos["alterar"]:
        c.valor = novo
        c.registrar("valor", texto, por)
        c.save()
    agenda.valor = novo
    agenda.observacoes = (agenda.observacoes + "\n" if agenda.observacoes else "") + \
        f"{timezone.localdate():%d/%m/%Y}: {texto}"
    agenda.save()
    contrato = agenda.contrato
    contrato.valor_mensal = novo
    contrato.save()
    resumo = f"{contrato.numero}: {texto} {len(grupos['alterar'])} emissão(ões) programada(s) atualizada(s)."
    if grupos["revisar"]:
        resumo += " Revise na tela: " + ", ".join(f"{c.competencia:%m/%Y} ({c.get_status_display().lower()})"
                                                 for c in grupos["revisar"]) + "."
    return resumo
