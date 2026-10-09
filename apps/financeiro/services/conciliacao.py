"""Importação idempotente do extrato e baixa integral mediante conferência."""
import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import contexto

from ..models import Lancamento, TransacaoExtrato
from .lancamentos import baixar


def registros_extrato(dados, nome):
    if len(dados) > 5_000_000:
        raise ValidationError("Extrato acima de 5 MB.")
    try:
        texto = dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = dados.decode("cp1252")
    if nome.lower().endswith(".ofx"):
        registros = []
        for bloco in re.findall(r"<STMTTRN\b[^>]*>(.*?)</STMTTRN>", texto, re.I | re.S):
            def campo(tag, bloco=bloco):
                m = re.search(fr"<{tag}\b[^>]*>\s*([^<\r\n]+)", bloco, re.I)
                return m.group(1).strip() if m else ""
            registros.append({"id": campo("FITID"), "data": campo("DTPOSTED")[:8],
                              "valor": campo("TRNAMT"), "descricao": campo("MEMO") or campo("NAME")})
        return registros
    if not nome.lower().endswith(".csv"):
        raise ValidationError("Use CSV ou OFX.")
    if not texto.strip():
        return []
    return list(csv.DictReader(io.StringIO(texto), delimiter=";" if ";" in texto.splitlines()[0] else ","))


def data_extrato(valor):
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            pass
    raise ValidationError("Data do extrato inválida.")


@transaction.atomic
def importar_extrato(empresa, conta, dados, nome):
    if conta.empresa_id != empresa.pk or not conta.ativo:
        raise ValidationError("Conta bancária inválida para a empresa.")
    linhas = registros_extrato(dados, nome)
    if not linhas or len(linhas) > 10000:
        raise ValidationError("Extrato vazio ou acima de 10.000 transações.")
    novos, repetidos = 0, 0
    digest = hashlib.sha256(dados).hexdigest()
    for linha in linhas:
        ident = (linha.get("id") or "").strip()
        descricao = (linha.get("descricao") or "").strip()
        if not ident or len(ident) > 200 or not descricao:
            raise ValidationError("Cada transação exige id bancário e descrição; importação cancelada.")
        data = data_extrato((linha.get("data") or "").strip())
        bruto = (linha.get("valor") or "").strip()
        if "," in bruto:
            bruto = bruto.replace(".", "").replace(",", ".")
        try:
            valor = Decimal(bruto)
            if not valor.is_finite() or not valor or valor != valor.quantize(Decimal("0.01")):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            raise ValidationError("Valor do extrato inválido.") from None
        if data > timezone.localdate():
            raise ValidationError("Extrato contém movimentação futura.")
        existente = TransacaoExtrato.objects.filter(conta_bancaria=conta, identificador_externo=ident).first()
        if existente:
            if existente.data != data or existente.valor != valor:
                raise ValidationError("Identificador bancário repetido com data/valor diferente; importação cancelada.")
            repetidos += 1
            continue
        obj = TransacaoExtrato(empresa=empresa, conta_bancaria=conta, identificador_externo=ident, data=data,
                              valor=valor, descricao=descricao[:300], hash_arquivo=digest)
        obj.full_clean()
        obj.save()
        novos += 1
    return novos, repetidos


@transaction.atomic
def conciliar(transacao, lancamento):
    transacao = TransacaoExtrato.objects.select_for_update().get(pk=transacao.pk)
    obj = Lancamento.objects.select_for_update().get(pk=lancamento.pk)
    atual = contexto.empresa_atual()
    if atual and atual.pk != transacao.empresa_id:
        raise ValidationError("Extrato de outra empresa.")
    if transacao.empresa_id != obj.empresa_id or obj.conta_bancaria_id not in (None, transacao.conta_bancaria_id):
        raise ValidationError("Transação e lançamento devem pertencer à mesma empresa e conta.")
    if transacao.lancamento_id or obj.conciliado or obj.status == "CANCELADO":
        raise ValidationError("Transação/lançamento já conciliado ou cancelado.")
    tipo = "RECEITA" if transacao.valor > 0 else "DESPESA"
    esperado = obj.valor_pago if obj.status == "PAGO" else obj.valor
    if obj.tipo != tipo or abs(transacao.valor) != esperado:
        raise ValidationError("Tipo ou valor diverge do lançamento. Confira juros, descontos e retenções antes de conciliar.")
    if obj.status != "PAGO":
        obj = baixar(obj, transacao.data, "TED", conta_bancaria=transacao.conta_bancaria)
    elif obj.data_pagamento != transacao.data:
        raise ValidationError("A data da baixa deve coincidir com o extrato.")
    obj.conta_bancaria = transacao.conta_bancaria
    obj.conciliado = True
    obj.save()
    transacao.lancamento = obj
    transacao.conciliada_em = timezone.now()
    transacao.save()
    return obj
