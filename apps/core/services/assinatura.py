"""Assinatura digital de PDFs (PAdES) com certificado ICP-Brasil A1 — da empresa ou do responsável.

Ordem de escolha: certificado de assinatura marcado como padrão → A1 da configuração fiscal. Sem certificado,
o PDF segue sem assinatura (e a tela avisa). A chave privada só existe em memória durante a assinatura.
"""

import io
import re

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.x509.oid import NameOID, ObjectIdentifier
from django.core.exceptions import ValidationError
from django.utils import timezone

from ..cripto import cifrar, decifrar, decifrar_texto
from ..models import CertificadoAssinatura


def _documento(cert):
    """CNPJ (OID 2.16.76.1.3.3) ou CPF (2.16.76.1.3.1, posições 8–19 do conteúdo) do certificado ICP-Brasil."""
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return ""
    for nome in san:
        if isinstance(nome, x509.OtherName):
            valor = re.sub(rb"[^0-9]", b"", nome.value[2:]).decode()
            if nome.type_id == ObjectIdentifier("2.16.76.1.3.3") and len(valor) >= 14:
                return valor[:14]
            if nome.type_id == ObjectIdentifier("2.16.76.1.3.1") and len(valor) >= 19:
                return valor[8:19]
    return ""


def abrir(dados: bytes, senha: str):
    try:
        chave, cert, _ = load_key_and_certificates(dados, senha.encode())
    except (ValueError, OSError):
        raise ValidationError("Não foi possível abrir o certificado: confira o arquivo .pfx/.p12 e a senha.") from None
    if chave is None or cert is None:
        raise ValidationError("O arquivo precisa conter o certificado e a chave privada.")
    agora = timezone.now()
    if not cert.not_valid_before_utc <= agora < cert.not_valid_after_utc:
        raise ValidationError("Certificado fora do período de validade.")
    return chave, cert


def cadastrar(empresa, dados: bytes, senha: str, tipo: str, padrao=True):
    if len(dados) > 2_000_000:
        raise ValidationError("O certificado deve ter no máximo 2 MB.")
    _, cert = abrir(dados, senha)
    if padrao:
        CertificadoAssinatura.objects.filter(empresa=empresa, padrao=True).update(padrao=False)
    obj = CertificadoAssinatura(empresa=empresa, tipo=tipo, padrao=padrao, documento=_documento(cert),
                                titular=cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value[:200],
                                validade_fim=cert.not_valid_after_utc,
                                impressao_sha256=cert.fingerprint(hashes.SHA256()).hex(),
                                arquivo_criptografado=cifrar(dados), senha_criptografada=cifrar(senha))
    obj.save()
    return obj


def credencial(empresa):
    """(pfx, senha, titular) do certificado a usar, ou None."""
    c = CertificadoAssinatura.objects.filter(empresa=empresa, ativo=True, padrao=True,
                                             validade_fim__gt=timezone.now()).first()
    if c:
        return decifrar(c.arquivo_criptografado), decifrar_texto(c.senha_criptografada), c.titular
    from apps.fiscal.models import ConfiguracaoFiscal

    config = ConfiguracaoFiscal.objects.select_related("certificado").filter(empresa=empresa).first()
    cert = config.certificado if config else None
    if cert and cert.ativo and cert.validade_fim > timezone.now():
        return decifrar(cert.arquivo_criptografado), decifrar_texto(cert.senha_criptografada), cert.nome
    return None


def titular_padrao(empresa):
    dados = credencial(empresa)
    if not dados:
        return None
    _, cert = abrir(dados[0], dados[1])
    return cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value


def localizar_ancora(pdf: bytes, texto: str):
    """(página, x, y) da última ocorrência de `texto` no PDF (coordenadas PDF), ou None."""
    from pypdf import PdfReader

    if not texto:
        return None
    try:
        leitor = PdfReader(io.BytesIO(pdf))
    except Exception:  # noqa: BLE001
        return None
    for indice in range(len(leitor.pages) - 1, -1, -1):
        achados = []

        def visitor(t, cm, tm, _fonte, _tamanho, achados=achados):
            if texto in (t or ""):
                # posição real = tm × cm (WeasyPrint escala via cm)
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                achados.append((x, y))
        leitor.pages[indice].extract_text(visitor_text=visitor)
        if achados:
            x, y = min(achados, key=lambda p: p[1])  # a mais baixa da página: o bloco de assinatura
            return indice, x, y
    return None


def caixa_carimbo(pdf: bytes, ancora: str):
    """Retângulo do carimbo visível, centrado na página e logo acima do nome da empresa."""
    from pypdf import PdfReader

    achado = localizar_ancora(pdf, ancora)
    if not achado:
        return None
    pagina, _x, y = achado
    largura_pagina = float(PdfReader(io.BytesIO(pdf)).pages[pagina].mediabox.width)
    largura, altura = 250, 46
    x1 = (largura_pagina - largura) / 2
    return pagina, (round(x1), round(y + 20), round(x1 + largura), round(y + 20 + altura))


def assinar_pdf(pdf: bytes, empresa, motivo="Documento aprovado no KS CENTRAL", local="Valença/BA", ancora=None):
    """Retorna (pdf_assinado, titular). Levanta ValidationError se não houver certificado utilizável.

    Com `ancora` (padrão: razão social da empresa) encontrada no PDF, a assinatura fica visível em um carimbo
    logo acima do nome; senão, é aplicada sem aparência visual (continua válida)."""
    from pyhanko import stamp
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.pdf_utils.text import TextBoxStyle
    from pyhanko.sign import fields, signers

    dados = credencial(empresa)
    if dados is None:
        raise ValidationError("Cadastre um certificado A1 em Configurações → Assinatura de documentos.")
    pfx, senha, _ = dados
    _, cert = abrir(pfx, senha)
    titular = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    signer = signers.SimpleSigner.load_pkcs12_data(pfx, other_certs=[], passphrase=senha.encode())
    escritor = IncrementalPdfFileWriter(io.BytesIO(pdf))
    nome_campo = "AssinaturaKSCENTRAL"
    existentes = 0
    try:
        from pyhanko.sign.fields import enumerate_sig_fields

        existentes = sum(1 for _ in enumerate_sig_fields(escritor.prev))
    except Exception:  # noqa: BLE001
        pass
    if existentes:
        nome_campo += str(existentes + 1)
    meta = signers.PdfSignatureMetadata(field_name=nome_campo, md_algorithm="sha256", reason=motivo,
                                        location=local, name=titular, subfilter=fields.SigSeedSubFilter.PADES)
    caixa = caixa_carimbo(pdf, ancora if ancora is not None else getattr(empresa, "razao_social", ""))
    estilo = None
    if caixa:
        fields.append_signature_field(escritor, fields.SigFieldSpec(nome_campo, on_page=caixa[0], box=caixa[1]))
        estilo = stamp.TextStampStyle(
            stamp_text="Assinado digitalmente por\n%(signer)s\nData: %(ts)s\nVerifique em validar.iti.gov.br",
            text_box_style=TextBoxStyle(font_size=7), border_width=1, timestamp_format="%d/%m/%Y %H:%M:%S %z")
    saida = signers.PdfSigner(meta, signer=signer, stamp_style=estilo).sign_pdf(escritor)
    return saida.getvalue(), titular


def assinar_se_possivel(pdf: bytes, empresa, motivo="Documento aprovado no KS CENTRAL", ancora=None):
    """Assina quando houver certificado; caso contrário devolve o PDF original. Retorna (pdf, titular|None)."""
    try:
        return assinar_pdf(pdf, empresa, motivo, ancora=ancora)
    except ValidationError:
        return pdf, None


def esta_assinado(pdf: bytes) -> bool:
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader

        return bool(PdfFileReader(io.BytesIO(pdf)).embedded_signatures)
    except Exception:  # noqa: BLE001
        return False
