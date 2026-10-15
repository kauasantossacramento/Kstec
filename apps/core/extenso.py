"""Valor monetário por extenso em português (até centenas de milhões)."""

from decimal import ROUND_HALF_UP, Decimal

UNIDADES = ["", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze",
            "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos",
            "novecentos"]


def _ate_mil(n):
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    c, resto = divmod(n, 100)
    partes = [CENTENAS[c]] if c else []
    if resto:
        if resto < 20:
            partes.append(UNIDADES[resto])
        else:
            d, u = divmod(resto, 10)
            partes.append(DEZENAS[d] + (f" e {UNIDADES[u]}" if u else ""))
    return " e ".join(partes)


def inteiro(n):
    if n == 0:
        return "zero"
    milhoes, resto = divmod(n, 1_000_000)
    milhares, unidades = divmod(resto, 1000)
    grupos = []  # (texto, valor do grupo)
    if milhoes:
        grupos.append((_ate_mil(milhoes) + (" milhão" if milhoes == 1 else " milhões"), milhoes))
    if milhares:
        grupos.append(("mil" if milhares == 1 else _ate_mil(milhares) + " mil", milhares))
    if unidades:
        grupos.append((_ate_mil(unidades), unidades))
    if len(grupos) == 1:
        return grupos[0][0]
    ultimo, valor = grupos[-1]
    conector = " e " if valor < 100 or valor % 100 == 0 else " "
    return ", ".join(t for t, _v in grupos[:-1]) + conector + ultimo


def reais(valor):
    valor = Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    inteiros = int(valor)
    centavos = int((valor - inteiros) * 100)
    partes = []
    if inteiros:
        texto = inteiro(inteiros)
        de = " de" if inteiros % 1_000_000 == 0 else ""
        partes.append(f"{texto}{de} {'real' if inteiros == 1 else 'reais'}")
    if centavos:
        partes.append(f"{inteiro(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
    return " e ".join(partes) or "zero real"
