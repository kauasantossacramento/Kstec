"""DPS fiscal em produção com valores explicitamente informados pelo emitente."""
import base64
import gzip
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from lxml import etree
from signxml import methods

from .homologacao import NS, AssinadorSemPrefixo, VerificadorSemPrefixo, elemento

URL = "https://sefin.nfse.gov.br/SefinNacional"
SCHEMAS = Path(__file__).resolve().parents[1] / "xml/schemas/producao"


def decimal_fiscal(valor, minimo, maximo):
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite() or not minimo <= numero <= maximo or numero != numero.quantize(Decimal("0.01")):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValidationError("Valor fiscal inválido; informe até duas casas decimais.") from None
    return format(numero, ".2f")


def validar_assinatura_schema(xml, a1, schemas=SCHEMAS, *, ambiente=1):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    doc = etree.fromstring(xml, parser)
    schema = esquema_dps(schemas, parser)
    if not schema.validate(doc):
        raise ValidationError([str(e) for e in schema.error_log])
    if doc.findtext(f"{{{NS}}}infDPS/{{{NS}}}prest/{{{NS}}}CNPJ") != a1.cnpj:
        raise ValidationError("CNPJ da DPS diferente do certificado.")
    if doc.findtext(f"{{{NS}}}infDPS/{{{NS}}}tpAmb") != str(ambiente):
        raise ValidationError(f"O cliente exige ambiente {ambiente}.")
    VerificadorSemPrefixo().verify(doc, x509_cert=a1.certificado.public_bytes(serialization.Encoding.PEM))
    return doc


def esquema_dps(schemas, parser):
    # O pacote oficial de 09/02/2026 contém âncoras de regex PCRE em TSSerieDPS.
    # No XML Schema/libxml2, ^ e $ são literais. Preserve o arquivo oficial e
    # normalize somente esse padrão em memória, mantendo o limite de cinco dígitos.
    class ResolverSerie(etree.Resolver):
        def resolve(self, url, pubid, context):
            if Path(url).name == "tiposSimples_v1.01.xsd":
                caminho = schemas / "tiposSimples_v1.01.xsd"
                dados = caminho.read_bytes().replace(b'value="^0{0,4}\\d{1,5}$"', b'value="0{0,4}[0-9]{1,5}"')
                return self.resolve_string(dados, context, base_url=str(caminho))
            return None

    parser.resolvers.add(ResolverSerie())
    return etree.XMLSchema(etree.parse(str(schemas / "DPS_v1.01.xsd"), parser))


def preparar_dps_producao(a1, numero, *, municipio, inscricao_municipal, tomador,
                         codigo_nacional, nbs, codigo_municipal, descricao, valor,
                         aliquota_iss, total_tributos_simples, data=None, serie="1", competencia=None, ambiente=1,
                         iss_retido=False):
    """ME/EPP do Simples, ISS tributável, sem regime especial.

    Sem retenção: regApTribSN=1, tpRetISSQN=1 e pAliq informado.
    ISS retido pelo tomador: espelha as NFS-e autorizadas 2600000000007–011 do portal E&L —
    regApTribSN=2, tpRetISSQN=2, sem pAliq (aplicada pela Sefin) e tomador com IM e endereço.
    Não infere a alíquota total a partir do ISS nem reutiliza massa sintética.
    """
    if not str(numero).isdigit() or not 1 <= int(numero) < 10**15:
        raise ValidationError("Número da DPS inválido.")
    if not str(serie).isdigit() or not 1 <= int(serie) < 80000:
        raise ValidationError("Informe uma série de emissão por aplicativo entre 1 e 79999.")
    if len(municipio) != 7 or not municipio.isdigit() or not inscricao_municipal:
        raise ValidationError("Informe município e inscrição municipal.")
    if ambiente not in (1, 2):
        raise ValidationError("Ambiente fiscal inválido.")
    if not descricao or not (tomador.get("cpf") or tomador.get("cnpj")) or not tomador.get("nome"):
        raise ValidationError("Informe descrição do serviço e tomador.")
    # O E&L grava a discriminação com quebras de linha trocadas por espaço; enviamos já normalizado.
    descricao = " ".join(descricao.split())
    valor = decimal_fiscal(valor, Decimal("0.01"), Decimal("999999999999.99"))
    aliquota = decimal_fiscal(aliquota_iss, Decimal("2"), Decimal("5"))
    total = decimal_fiscal(total_tributos_simples, Decimal("0"), Decimal("100"))
    agora = data or datetime.now(ZoneInfo("America/Bahia"))
    identificador = f"DPS{municipio}2{a1.cnpj}{int(serie):05d}{int(numero):015d}"
    raiz = etree.Element(f"{{{NS}}}DPS", nsmap={None: NS}, versao="1.01")
    inf = elemento(raiz, "infDPS")
    inf.set("Id", identificador)
    for tag, conteudo in [("tpAmb", ambiente), ("dhEmi", agora.isoformat(timespec="seconds")),
                          ("verAplic", "KSCENTRAL_1"), ("serie", int(serie)), ("nDPS", int(numero)),
                          ("dCompet", (competencia or agora.date()).isoformat()), ("tpEmit", 1), ("cLocEmi", municipio)]:
        elemento(inf, tag, conteudo)
    prest = elemento(inf, "prest")
    elemento(prest, "CNPJ", a1.cnpj)
    elemento(prest, "IM", inscricao_municipal)
    regime = elemento(prest, "regTrib")
    for tag, conteudo in [("opSimpNac", 3), ("regApTribSN", 2 if iss_retido else 1), ("regEspTrib", 0)]:
        elemento(regime, tag, conteudo)
    toma = elemento(inf, "toma")
    elemento(toma, "CPF" if tomador.get("cpf") else "CNPJ", tomador.get("cpf") or tomador["cnpj"])
    if tomador.get("im"):
        elemento(toma, "IM", tomador["im"])
    elemento(toma, "xNome", tomador["nome"])
    end = tomador.get("endereco") or {}
    if iss_retido and not (end.get("municipio_ibge") and end.get("cep") and end.get("logradouro") and end.get("bairro")):
        raise ValidationError("ISS retido exige o endereço completo do tomador (município, CEP, logradouro e bairro).")
    if end.get("municipio_ibge") and end.get("cep") and end.get("logradouro") and end.get("bairro"):
        bloco = elemento(toma, "end")
        nacional = elemento(bloco, "endNac")
        elemento(nacional, "cMun", end["municipio_ibge"])
        elemento(nacional, "CEP", end["cep"])
        elemento(bloco, "xLgr", end["logradouro"][:255])
        elemento(bloco, "nro", (end.get("numero") or "S/N")[:60])
        if end.get("complemento"):
            elemento(bloco, "xCpl", end["complemento"][:156])
        elemento(bloco, "xBairro", end["bairro"][:60])
    serv = elemento(inf, "serv")
    elemento(elemento(serv, "locPrest"), "cLocPrestacao", municipio)
    codigo = elemento(serv, "cServ")
    elemento(codigo, "cTribNac", codigo_nacional)
    elemento(codigo, "xDescServ", descricao)
    elemento(codigo, "cNBS", nbs)
    if codigo_municipal:
        elemento(codigo, "cIntContrib", codigo_municipal)
    valores = elemento(inf, "valores")
    elemento(elemento(valores, "vServPrest"), "vServ", valor)
    trib = elemento(valores, "trib")
    mun = elemento(trib, "tribMun")
    elemento(mun, "tribISSQN", 1)
    elemento(mun, "tpRetISSQN", 2 if iss_retido else 1)
    if not iss_retido:
        elemento(mun, "pAliq", aliquota)
    elemento(elemento(trib, "totTrib"), "pTotTribSN", total)
    signer = AssinadorSemPrefixo(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                                c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    signer.namespaces = {None: "http://www.w3.org/2000/09/xmldsig#"}
    assinado = signer.sign(raiz, key=a1.chave, cert=a1.certificado.public_bytes(serialization.Encoding.PEM),
                          reference_uri=f"#{identificador}")
    xml = etree.tostring(assinado, encoding="UTF-8", xml_declaration=True)
    validar_assinatura_schema(xml, a1, ambiente=ambiente)
    return identificador, xml


def corpo_producao(xml, a1, schemas=SCHEMAS):
    validar_assinatura_schema(xml, a1, schemas)
    return {"dpsXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii")}
