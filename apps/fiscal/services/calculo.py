"""Cálculo preparatório conforme seção 6.8 do plano; alíquotas vêm do contador."""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

ZERO = Decimal("0")


def decimal_exato(valor):
    if isinstance(valor, float):
        raise ValidationError("Valores monetários não podem usar float.")
    try:
        numero = Decimal(valor)
    except (TypeError, ValueError, ArithmeticError):
        raise ValidationError("Valor decimal inválido.")
    if not numero.is_finite() or numero < ZERO:
        raise ValidationError("Valores devem ser finitos e não negativos.")
    return numero


def r2(valor):
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular(nota, perfil):
    """Calcula sem persistir. Desconto condicionado afeta somente o líquido."""
    valores = {campo: decimal_exato(getattr(nota, campo)) for campo in (
        "valor_servicos", "valor_deducoes", "desconto_incondicionado", "desconto_condicionado", "outras_retencoes",
    )}
    vs = valores["valor_servicos"]
    base = vs - valores["valor_deducoes"] - valores["desconto_incondicionado"]
    if base < ZERO:
        raise ValidationError("Deduções e desconto incondicionado excedem o valor dos serviços.")
    aliquota = nota.aliquota_iss if nota.empresa.optante_simples else perfil.aliquota_iss
    if nota.empresa.regime_tributario == nota.empresa.Regime.MEI:
        aliquota = ZERO
    if aliquota is None:
        raise ValidationError("Informe a alíquota do Simples para esta competência.")
    aliquota = decimal_exato(aliquota)
    if aliquota > 100:
        raise ValidationError("Alíquota inválida.")
    calculados = {"base_calculo": r2(base), "aliquota_iss": aliquota,
                  "valor_iss": r2(base * aliquota / 100), "iss_retido": perfil.iss_retido}
    calculados["valor_iss_retido"] = calculados["valor_iss"] if perfil.iss_retido else ZERO
    for tributo in ("ir", "inss", "pis", "cofins", "csll"):
        taxa = decimal_exato(getattr(perfil, f"aliquota_{tributo}"))
        if taxa > 100:
            raise ValidationError("Alíquota inválida.")
        calculados[f"valor_{tributo}"] = r2(vs * taxa / 100) if getattr(perfil, f"reter_{tributo}") else ZERO
    retencoes = sum(calculados[f"valor_{t}"] for t in ("ir", "inss", "pis", "cofins", "csll", "iss_retido"))
    liquido = vs - retencoes - valores["outras_retencoes"] - valores["desconto_incondicionado"] - valores["desconto_condicionado"]
    if liquido < ZERO:
        raise ValidationError("Descontos e retenções excedem o valor dos serviços.")
    calculados["valor_liquido"] = r2(liquido)
    for campo, valor in calculados.items():
        setattr(nota, campo, valor)
    return nota
