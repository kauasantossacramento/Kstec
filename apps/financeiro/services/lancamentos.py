"""Persistência, baixa integral e cancelamento com transações e validação por empresa."""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import contexto

from ..models import CategoriaFinanceira, CentroCusto, Lancamento


def valor_decimal(valor):
    if isinstance(valor, float):
        raise ValidationError("Use valores decimais, nunca float.")
    try:
        d = Decimal(valor)
    except (ValueError, TypeError, ArithmeticError):
        raise ValidationError("Valor monetário inválido.")
    if not d.is_finite() or d < 0:
        raise ValidationError("Valor monetário deve ser finito e não negativo.")
    try:
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except ArithmeticError:
        raise ValidationError("Valor monetário excede a precisão permitida.")


def validar_categoria(tipo, grupo):
    if tipo not in CategoriaFinanceira.Tipo.values or grupo not in CategoriaFinanceira.Grupo.values:
        raise ValidationError("Tipo ou grupo financeiro inválido.")
    if tipo == "RECEITA" and grupo not in ("RECEITA_BRUTA", "NAO_OPERACIONAL"):
        raise ValidationError("Receitas devem usar receita bruta ou não operacional.")
    if tipo == "DESPESA" and grupo == "RECEITA_BRUTA":
        raise ValidationError("Despesas não podem compor receita bruta.")


def validar(lancamento):
    for campo in ("pessoa", "categoria", "centro_custo", "conta_bancaria", "nota_fiscal"):
        obj = getattr(lancamento, campo, None)
        if obj is not None and obj.empresa_id != lancamento.empresa_id:
            raise ValidationError("Todos os vínculos financeiros devem pertencer à mesma empresa.")
    if lancamento.categoria.tipo != lancamento.tipo:
        raise ValidationError("A categoria deve ter o mesmo tipo do lançamento.")
    validar_categoria(lancamento.categoria.tipo, lancamento.categoria.grupo_dre)
    if not lancamento.categoria.ativo or (lancamento.conta_bancaria and not lancamento.conta_bancaria.ativo) or not lancamento.centro_custo.ativo:
        raise ValidationError("Selecione conta, categoria e centro de custo ativos.")
    lancamento.valor = valor_decimal(lancamento.valor)
    if lancamento.valor <= 0:
        raise ValidationError("O valor do lançamento deve ser maior que zero.")


@transaction.atomic
def salvar(lancamento):
    if not lancamento._state.adding:
        atual = Lancamento.objects.select_for_update().get(pk=lancamento.pk, empresa=lancamento.empresa)
        if atual.status in (Lancamento.Status.PAGO, Lancamento.Status.CANCELADO):
            raise ValidationError("Lançamentos pagos ou cancelados não podem ser editados.")
        if atual.nota_fiscal_id:
            raise ValidationError("O recebível de nota fiscal não pode ser editado manualmente.")
        lancamento.status = atual.status
    validar(lancamento)
    lancamento.full_clean()
    lancamento.save()
    return lancamento


def centro_contrato(contrato):
    centro, _ = CentroCusto.objects.get_or_create(
        contrato=contrato, defaults={"empresa": contrato.empresa, "nome": f"Contrato {contrato.numero} · {str(contrato.pk)[:8]}"},
    )
    return centro


def _bloquear(lancamento):
    empresa = contexto.empresa_atual()
    if empresa is not None and empresa.pk != lancamento.empresa_id:
        raise ValidationError("Lançamento de outra empresa.")
    return Lancamento.objects.select_for_update().get(pk=lancamento.pk, empresa_id=lancamento.empresa_id)


@transaction.atomic
def baixar(lancamento, data_pagamento, forma_pagamento, juros=Decimal("0"), multa=Decimal("0"),
           desconto=Decimal("0"), ordem_bancaria="", data_liquidacao=None, conta_bancaria=None):
    obj = _bloquear(lancamento)
    if obj.status in (obj.Status.PAGO, obj.Status.CANCELADO):
        raise ValidationError("Este lançamento já foi pago ou cancelado.")
    if conta_bancaria:
        if conta_bancaria.empresa_id != obj.empresa_id or not conta_bancaria.ativo:
            raise ValidationError("Conta bancária inválida para a empresa.")
        obj.conta_bancaria = conta_bancaria
    if not obj.conta_bancaria_id:
        raise ValidationError("Selecione a conta bancária do recebimento/pagamento.")
    if data_pagamento > timezone.localdate():
        raise ValidationError("O pagamento não pode ter data futura.")
    if forma_pagamento not in Lancamento.Forma.values:
        raise ValidationError("Forma de pagamento inválida.")
    if forma_pagamento == Lancamento.Forma.OB and not ordem_bancaria.strip():
        raise ValidationError("Informe o número da ordem bancária.")
    if data_liquidacao and data_liquidacao > data_pagamento:
        raise ValidationError("A liquidação não pode ser posterior ao pagamento.")
    obj.juros, obj.multa, obj.desconto = (valor_decimal(x) for x in (juros, multa, desconto))
    obj.valor_pago = obj.valor + obj.juros + obj.multa - obj.desconto
    if obj.valor_pago <= 0:
        raise ValidationError("Desconto deve ser menor que o valor a pagar.")
    obj.data_pagamento = data_pagamento
    obj.forma_pagamento = forma_pagamento
    obj.ordem_bancaria = ordem_bancaria.strip()
    obj.data_liquidacao = data_liquidacao
    obj.status = obj.Status.PAGO
    obj.full_clean()
    obj.save()
    return obj


@transaction.atomic
def cancelar(lancamento, motivo):
    obj = _bloquear(lancamento)
    if obj.status in (obj.Status.PAGO, obj.Status.CANCELADO):
        raise ValidationError("Não é possível cancelar lançamento pago ou já cancelado.")
    if not motivo.strip():
        raise ValidationError("Informe o motivo do cancelamento.")
    obj.status = obj.Status.CANCELADO
    obj.motivo_cancelamento = motivo.strip()
    obj.full_clean()
    obj.save()
    return obj


def marcar_atrasados(empresa=None):
    qs = Lancamento.objects.filter(status__in=["PREVISTO", "PENDENTE"], data_vencimento__lt=timezone.localdate())
    if empresa:
        qs = qs.filter(empresa=empresa)
    total = 0
    # save() preserva o histórico que update() não registra.
    for obj in qs:
        with transaction.atomic():
            obj = Lancamento.objects.select_for_update().get(pk=obj.pk)
            if obj.status not in ("PREVISTO", "PENDENTE"):
                continue
            obj.status = obj.Status.ATRASADO
            obj.save(update_fields=["status", "atualizado_em"])
            total += 1
    return total
