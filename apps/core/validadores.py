"""Validação e formatação de documentos brasileiros."""

import re

from django.core.exceptions import ValidationError


def so_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    cpf = so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(cpf[j]) * ((i + 1) - j) for j in range(i))
        dv = (soma * 10) % 11 % 10
        if dv != int(cpf[i]):
            return False
    return True


def cnpj_valido(cnpj: str) -> bool:
    cnpj = so_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(len(pesos)))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(cnpj[pos]):
            return False
    return True


def validar_cpf_cnpj(valor: str):
    d = so_digitos(valor)
    if len(d) == 11 and cpf_valido(d):
        return
    if len(d) == 14 and cnpj_valido(d):
        return
    raise ValidationError("CPF/CNPJ inválido (dígito verificador não confere).")


def validar_cpf_cnpj_opcional(valor: str):
    """Aceita vazio (documento ainda não emitido); se informado, valida os dígitos."""
    if so_digitos(valor):
        validar_cpf_cnpj(valor)


def validar_cnpj(valor: str):
    if not cnpj_valido(valor):
        raise ValidationError("CNPJ inválido.")


def formatar_doc(valor: str | None) -> str:
    d = so_digitos(valor)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return valor or ""


def formatar_cep(valor: str | None) -> str:
    d = so_digitos(valor)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (valor or "")


def normalizar_telefone(valor: str | None) -> str:
    """Telefone brasileiro em dígitos E.164 (55 + DDD + número). Vazio se inválido."""
    d = so_digitos(valor)
    if d.startswith("00"):
        d = d[2:]
    if len(d) in (10, 11):
        d = "55" + d
    if not (d.startswith("55") and len(d) in (12, 13)):
        return ""
    return d


def validar_telefone(valor: str):
    if not normalizar_telefone(valor):
        raise ValidationError("Informe DDD e número, por exemplo (75) 99999-0000.")


def formatar_telefone(valor: str | None) -> str:
    d = normalizar_telefone(valor)
    if not d:
        return valor or ""
    ddd, numero = d[2:4], d[4:]
    return f"({ddd}) {numero[:-4]}-{numero[-4:]}"
