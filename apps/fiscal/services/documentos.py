"""Validação do XML recebido de um canal fiscal autenticado."""
import base64
import gzip
import io
from datetime import UTC, datetime

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from lxml import etree
from signxml import DigestAlgorithm, SignatureConfiguration, SignatureMethod

from .homologacao import NS, VerificadorSemPrefixo
from .producao import SCHEMAS, esquema_dps


def descompactar_nfse(retorno):
    try:
        dados = base64.b64decode(retorno["nfseXmlGZipB64"], validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(dados)) as f:
            xml = f.read(5_000_001)
        if len(xml) > 5_000_000:
            raise ValueError
        return xml
    except (KeyError, ValueError, TypeError, OSError, EOFError):
        raise ValidationError("Retorno sem XML de NFS-e válido.") from None


def conteudo(no):
    """Estrutura comparável do XML. Espaços em branco são normalizados: o emissor municipal (E&L) substitui
    quebras de linha da discriminação por espaço ao autorizar a NFS-e."""
    texto = " ".join((no.text or "").split())
    return no.tag, dict(no.attrib), texto, [conteudo(filho) for filho in no]


def validar_nfse(xml, id_dps, ambiente, cnpj, chave, dps_enviada=None):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        doc = etree.fromstring(xml, parser)
        esquema_dps(SCHEMAS, parser)
        schema = etree.XMLSchema(etree.parse(str(SCHEMAS / "NFSe_v1.01.xsd"), parser))
        schema.assertValid(doc)
        inf = doc.find(f"{{{NS}}}infNFSe")
        dps = doc.find(f".//{{{NS}}}DPS/{{{NS}}}infDPS")
        if (not chave.isdigit() or len(chave) != 50 or inf is None or dps is None
                or inf.get("Id") != "NFS" + chave or dps.get("Id") != id_dps
                or dps.findtext(f"{{{NS}}}tpAmb") != str(ambiente)
                or dps.findtext(f"{{{NS}}}prest/{{{NS}}}CNPJ") != cnpj
                or inf.findtext(f"{{{NS}}}cStat") != "100"):
            raise ValidationError("Identidade, ambiente, emitente ou situação da NFS-e não conferem.")
        if dps_enviada:
            esperado = etree.fromstring(dps_enviada, parser).find(f"{{{NS}}}infDPS")
            if conteudo(dps) != conteudo(esperado):
                raise ValidationError("Dados autorizados divergem da DPS enviada.")
        cert_texto = doc.findtext('.//{http://www.w3.org/2000/09/xmldsig#}X509Certificate') or ""
        cert_der = base64.b64decode("".join(cert_texto.split()), validate=True)
        cert = x509.load_der_x509_certificate(cert_der)
        if not cert.not_valid_before_utc <= datetime.now(UTC) < cert.not_valid_after_utc:
            raise ValidationError("Certificado do autorizador fora da validade.")
        verificado = VerificadorSemPrefixo().verify(doc, x509_cert=cert.public_bytes(serialization.Encoding.PEM),
            expect_config=SignatureConfiguration(
                signature_methods=frozenset([SignatureMethod.RSA_SHA1, SignatureMethod.RSA_SHA256]),
                digest_algorithms=frozenset([DigestAlgorithm.SHA1, DigestAlgorithm.SHA256])))
        if verificado.signed_xml.get("Id") != inf.get("Id"):
            raise ValidationError("A assinatura não cobre a NFS-e.")
        return doc
    except ValidationError:
        raise
    except Exception as erro:
        # Nunca repassa XML, certificados ou dados pessoais nas mensagens da interface.
        raise ValidationError(f"Validação do documento fiscal falhou ({type(erro).__name__}).") from None
