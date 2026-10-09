"""Consulta SOAP de RPS no endpoint confirmado de Valença/BA. Não emite notas."""
from django.core.exceptions import ValidationError
from lxml import etree

URL_VALENCA = "https://ba-valenca-pm-nfs-backend.cloud.el.com.br/producao/NfseWSService"
NS = "http://www.abrasf.org.br/nfse.xsd"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
OPERACAO = "http://nfse.abrasf.org.br"


def mensagens_resposta(xml):
    """Extrai erros sem divulgar notas; resposta vazia não representa sucesso."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    doc = etree.fromstring(xml, parser)
    consulta = '//*[local-name()="Codigo" or local-name()="Mensagem" or local-name()="faultstring"]/text()'
    mensagens = doc.xpath(consulta)
    internos = doc.xpath('//*[local-name()="outputXML"]/text()')
    for valor in internos:
        mensagens.extend(etree.fromstring(valor.encode(), parser).xpath(consulta))
    if not mensagens and not internos:
        mensagens.append("Resposta SOAP sem resultado de negócio; consulta não validada.")
    return mensagens


def consulta_rps(cnpj, numero, serie, inscricao_municipal=""):
    if not cnpj.isdigit() or len(cnpj) != 14 or not str(numero).isdigit() or not str(serie):
        raise ValidationError("Informe CNPJ, número e série válidos.")
    dados = etree.Element(f"{{{NS}}}ConsultarNfseRpsEnvio", nsmap={None: NS})
    identificacao = etree.SubElement(dados, f"{{{NS}}}IdentificacaoRps")
    for tag, texto in [("Numero", numero), ("Serie", serie), ("Tipo", 1)]:
        etree.SubElement(identificacao, f"{{{NS}}}{tag}").text = str(texto)
    prest = etree.SubElement(dados, f"{{{NS}}}Prestador")
    etree.SubElement(etree.SubElement(prest, f"{{{NS}}}CpfCnpj"), f"{{{NS}}}Cnpj").text = cnpj
    if inscricao_municipal:
        etree.SubElement(prest, f"{{{NS}}}InscricaoMunicipal").text = inscricao_municipal
    envelope = etree.Element(f"{{{SOAP}}}Envelope", nsmap={"soapenv": SOAP, "nfse": OPERACAO})
    etree.SubElement(envelope, f"{{{SOAP}}}Header")
    body = etree.SubElement(envelope, f"{{{SOAP}}}Body")
    op = etree.SubElement(body, f"{{{OPERACAO}}}ConsultarNfsePorRps")
    request = etree.SubElement(op, f"{{{OPERACAO}}}ConsultarNfsePorRpsRequest")
    etree.SubElement(request, "nfseCabecMsg").text = etree.CDATA(
        '<cabecalho xmlns="http://www.abrasf.org.br/nfse.xsd"><versaoDados>2.04</versaoDados></cabecalho>')
    etree.SubElement(request, "nfseDadosMsg").text = etree.CDATA(etree.tostring(dados, encoding="unicode"))
    return etree.tostring(envelope, encoding="UTF-8", xml_declaration=True)
