"""Previsões por competência; repetir a geração não duplica lançamentos."""
from calendar import monthrange

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.contratos.models import somar_meses

from ..models import Lancamento, Recorrencia
from .lancamentos import validar


def validar_recorrencia(obj):
    if obj.fim and obj.fim < obj.inicio:
        raise ValidationError("O fim deve ser igual ou posterior ao início.")
    validar(Lancamento(empresa=obj.empresa, **modelo(obj), data_competencia=obj.inicio, data_vencimento=obj.inicio))


def modelo(obj):
    return {campo: getattr(obj, campo) for campo in ("tipo", "descricao", "pessoa", "categoria", "centro_custo", "conta_bancaria", "valor")}


@transaction.atomic
def gerar(obj, hoje=None):
    obj = Recorrencia.objects.select_for_update().get(pk=obj.pk, empresa_id=obj.empresa_id)
    if not obj.ativo:
        return 0
    validar_recorrencia(obj)
    obj.full_clean()
    hoje = hoje or timezone.localdate()
    limite = somar_meses(hoje.replace(day=1), 12)
    mes = max(obj.inicio.replace(day=1), hoje.replace(day=1))
    total = 0
    while mes < limite:
        vencimento = mes.replace(day=min(obj.dia, monthrange(mes.year, mes.month)[1]))
        incluir = obj.inicio <= vencimento and (obj.fim is None or vencimento <= obj.fim)
        if obj.frequencia == "ANUAL":
            incluir = incluir and mes.month == obj.inicio.month
        if incluir and not Lancamento.objects.filter(empresa=obj.empresa, recorrencia=obj, data_competencia=mes).exists():
            novo = Lancamento(empresa=obj.empresa, recorrencia=obj, data_competencia=mes, data_vencimento=vencimento,
                               status="PREVISTO", **modelo(obj))
            validar(novo)
            novo.full_clean()
            novo.save()
            total += 1
        mes = somar_meses(mes, 1)
    return total
