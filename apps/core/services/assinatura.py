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


def assinar_pdf(pdf: bytes, empresa, motivo="Documento aprovado no KS CENTRAL", local="Valença/BA"):
    """Retorna (pdf_assinado, titular). Levanta ValidationError se não houver certificado utilizável."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers

    dados = credencial(empresa)
    if dados is None:
        raise ValidationError("Cadastre um certificado A1 em Configurações → Assinatura de documentos.")
    pfx, senha, _ = dados
    _, cert = abrir(pfx, senha)
    titular = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    signer = signers.SimpleSigner.load_pkcs12_data(pfx, other_certs=[], passphrase=senha.encode())
    escritor = IncrementalPdfFileWriter(io.BytesIO(pdf))
    meta = signers.PdfSignatureMetadata(field_name="AssinaturaKSCENTRAL", md_algorithm="sha256", reason=motivo,
                                        location=local, name=titular, subfilter=fields.SigSeedSubFilter.PADES)
    saida = signers.sign_pdf(escritor, meta, signer=signer)
    return saida.getvalue(), titular


def assinar_se_possivel(pdf: bytes, empresa, motivo="Documento aprovado no KS CENTRAL"):
    """Assina quando houver certificado; caso contrário devolve o PDF original. Retorna (pdf, titular|None)."""
    try:
        return assinar_pdf(pdf, empresa, motivo)
    except ValidationError:
        return pdf, None


def esta_assinado(pdf: bytes) -> bool:
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader

        return bool(PdfFileReader(io.BytesIO(pdf)).embedded_signatures)
    except Exception:  # noqa: BLE001
        return False
