"""DPS de teste de R$ 1,00, exclusivamente em produção restrita.

Os parâmetros tributários abaixo são uma massa de homologação; não alteram o
cadastro da empresa nem são utilizáveis para emitir documentos em produção.
"""
import base64
import gzip
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from lxml import etree
from signxml import XMLSigner, XMLVerifier, methods

NS = "http://www.sped.fazenda.gov.br/nfse"
SCHEMAS = Path(__file__).resolve().parents[1] / "xml" / "schemas" / "restrita"
URL = "https://sefin.producaorestrita.nfse.gov.br/SefinNacional"


class CanonicalizacaoIsolada:
    def _c14n(self, nodes, algorithm, inclusive_ns_prefixes=None):
        lista = nodes if isinstance(nodes, list) else [nodes]
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        isolados = [etree.fromstring(etree.tostring(no), parser) for no in lista]
        return super()._c14n(isolados, algorithm, inclusive_ns_prefixes)


class VerificadorSemPrefixo(CanonicalizacaoIsolada, XMLVerifier):
    pass


class AssinadorSemPrefixo(CanonicalizacaoIsolada, XMLSigner):
    def _ds_tag(self, tag):
        # signxml 5.1 gera tags sem QName quando ds é o namespace padrão.
        # Use nomes expandidos para manter o mesmo namespace antes/depois de serializar.
        return etree.QName("http://www.w3.org/2000/09/xmldsig#", tag)


def elemento(pai, tag, texto=None):
    obj = etree.SubElement(pai, f"{{{NS}}}{tag}")
    if texto is not None:
        obj.text = str(texto)
    return obj


def preparar_dps(a1, numero, municipio="2932903", data=None, *, inscricao_municipal="", tomador=None,
                 codigo_municipal="", codigo_nacional="010701", nbs="115013000", schemas=SCHEMAS,
                 aliquota_iss_teste=None):
    agora = data or datetime.now(ZoneInfo("America/Bahia"))
    serie = "89999"
    if not str(numero).isdigit() or not 1 <= int(numero) < 10**15:
        raise ValidationError("Número da DPS de teste inválido.")
    if len(municipio) != 7 or not municipio.isdigit():
        raise ValidationError("Município inválido.")
    identificador = f"DPS{municipio}2{a1.cnpj}{serie}{int(numero):015d}"
    raiz = etree.Element(f"{{{NS}}}DPS", nsmap={None: NS}, versao="1.01")
    inf = elemento(raiz, "infDPS")
    inf.set("Id", identificador)
    for tag, valor in [("tpAmb", 2), ("dhEmi", agora.isoformat(timespec="seconds")), ("verAplic", "KSCENTRAL_TESTE_1"),
                       ("serie", serie), ("nDPS", int(numero)), ("dCompet", agora.date().isoformat()),
                       ("tpEmit", 1), ("cLocEmi", municipio)]:
        elemento(inf, tag, valor)
    prest = elemento(inf, "prest")
    elemento(prest, "CNPJ", a1.cnpj)
    if inscricao_municipal:
        elemento(prest, "IM", inscricao_municipal)
    regime = elemento(prest, "regTrib")
    elemento(regime, "opSimpNac", 3)
    elemento(regime, "regApTribSN", 1)
    elemento(regime, "regEspTrib", 0)
    if tomador:
        toma = elemento(inf, "toma")
        elemento(toma, "CPF", tomador["cpf"])
        elemento(toma, "xNome", tomador["nome"])
    serv = elemento(inf, "serv")
    elemento(elemento(serv, "locPrest"), "cLocPrestacao", municipio)
    codigo = elemento(serv, "cServ")
    elemento(codigo, "cTribNac", codigo_nacional)
    descricao = "SUPORTE TECNICO" if codigo_nacional == "010701" else "ANALISE E DESENVOLVIMENTO DE SISTEMAS"
    elemento(codigo, "xDescServ", f"TESTE DE INTEGRACAO KS CENTRAL - HOMOLOGACAO SEM VALOR FISCAL - {descricao}")
    elemento(codigo, "cNBS", nbs)
    if codigo_municipal:
        elemento(codigo, "cIntContrib", codigo_municipal)
    valores = elemento(inf, "valores")
    elemento(elemento(valores, "vServPrest"), "vServ", "1.00")
    trib = elemento(valores, "trib")
    mun = elemento(trib, "tribMun")
    elemento(mun, "tribISSQN", 1)
    elemento(mun, "tpRetISSQN", 1)
    if aliquota_iss_teste is not None:
        elemento(mun, "pAliq", aliquota_iss_teste)
    elemento(elemento(trib, "totTrib"), "pTotTribSN", "6.00")
    from cryptography.hazmat.primitives import serialization

    cert_pem = a1.certificado.public_bytes(serialization.Encoding.PEM)
    signer = AssinadorSemPrefixo(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                       c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    signer.namespaces = {None: "http://www.w3.org/2000/09/xmldsig#"}
    assinado = signer.sign(raiz, key=a1.chave, cert=cert_pem, reference_uri=f"#{identificador}")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    # Resolva os namespaces do XML serializado, inclusive o namespace padrão da assinatura.
    assinado = etree.fromstring(etree.tostring(assinado), parser)
    schema = etree.XMLSchema(etree.parse(str(schemas / "DPS_v1.01.xsd"), parser))
    if not schema.validate(assinado):
        raise ValidationError([str(e) for e in schema.error_log])
    VerificadorSemPrefixo().verify(assinado, x509_cert=cert_pem)
    return identificador, etree.tostring(assinado, encoding="UTF-8", xml_declaration=True)


def corpo_envio(xml):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    doc = etree.fromstring(xml, parser)
    if doc.findtext(f"{{{NS}}}infDPS/{{{NS}}}tpAmb") != "2":
        raise ValidationError("O cliente de teste aceita exclusivamente produção restrita.")
    if doc.findtext(f"{{{NS}}}infDPS/{{{NS}}}valores/{{{NS}}}vServPrest/{{{NS}}}vServ") != "1.00":
        raise ValidationError("O teste aceita exclusivamente R$ 1,00.")
    return {"dpsXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii")}
