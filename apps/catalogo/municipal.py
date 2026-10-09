"""Referências municipais com origem e código de integração independente do item LC."""
import csv
import io
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from pypdf import PdfReader

from .models import ServicoMunicipal


def linhas_pdf(dados):
    texto = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(dados)).pages)
    inicio = re.search(r"(?m)^\s*ANEXO I\s*$", texto)
    if not inicio:
        raise ValidationError("Lista ANEXO I não encontrada no PDF municipal.")
    texto = texto[inicio.end():]
    fim = re.search(r"(?m)^\s*ANEXO II\s*$", texto)
    if fim:
        texto = texto[:fim.start()]
    padrao = r"(?m)^\s*(\d{1,2})\.(\d{2})\s*[–−-]\s*(.*?)(?=^\s*\d{1,2}(?:\.\d{2})?\s*[–−-]|\Z)"
    return [{"item_lc116": f"{int(m[0]):02d}.{m[1]}", "descricao": re.sub(r"\s+", " ", m[2]).strip(),
             "codigo_integracao": ""} for m in re.findall(padrao, texto, re.MULTILINE | re.DOTALL)]


@transaction.atomic
def importar_municipais(dados, nome, municipio, fonte, confirmar_codigos=False):
    if not re.fullmatch(r"[0-9]{7}", municipio) or not fonte.startswith("https://"):
        raise ValidationError("Informe município IBGE e URL HTTPS da fonte.")
    if len(dados) > 20_000_000:
        raise ValidationError("Arquivo municipal acima de 20 MB.")
    if nome.lower().endswith(".pdf"):
        linhas = linhas_pdf(dados)
    elif nome.lower().endswith(".csv"):
        try:
            texto = dados.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("Salve o CSV municipal em UTF-8.") from None
        if not texto.strip():
            raise ValidationError("Arquivo municipal vazio; tabela preservada.")
        leitor = csv.DictReader(io.StringIO(texto), delimiter=";" if ";" in texto.splitlines()[0] else ",")
        linhas = list(leitor)
    else:
        raise ValidationError("Use PDF do Anexo I ou CSV com item_lc116, descricao e codigo_integracao.")
    if not linhas:
        raise ValidationError("Nenhum serviço municipal encontrado; tabela preservada.")
    total = 0
    vistos = set()
    for linha in linhas:
        item = linha.get("item_lc116", "").strip()
        descricao = linha.get("descricao", "").strip()
        codigo = (linha.get("codigo_integracao") or "").strip()
        if not re.fullmatch(r"[0-9]{2}\.[0-9]{2}", item) or not descricao or item in vistos or len(codigo) > 20:
            raise ValidationError("Registro municipal inválido ou repetido; importação cancelada.")
        vistos.add(item)
        obj, _ = ServicoMunicipal.objects.get_or_create(municipio_ibge=municipio, item_lc116=item,
                    defaults={"descricao": descricao, "fonte": fonte})
        obj.descricao = descricao
        # A lista legal não fornece o cIntContrib E&L: não derive nem apague um código confirmado.
        if codigo:
            obj.codigo_integracao = codigo
            obj.codigo_confirmado = confirmar_codigos
        if not obj.codigo_confirmado:
            obj.fonte = fonte
        obj.save()
        total += 1
    return total
