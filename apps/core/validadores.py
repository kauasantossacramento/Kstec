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
