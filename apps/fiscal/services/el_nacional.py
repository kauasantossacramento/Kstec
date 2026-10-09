"""API municipal E&L DPS documentada no portal de Valença/BA.

O método enviar_homologacao transmite exclusivamente em homologação. Produção
usa o comando emitir_nfse_producao com validação e registro próprios.
Consultas não emitem notas.
O token é mantido em memória; URLs autenticadas nunca são retornadas em erros.
"""
import base64
import gzip
import io
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from lxml import etree

from .homologacao import NS, VerificadorSemPrefixo, corpo_envio

BASE = "https://ba-valenca-pm-nfs-backend.cloud.el.com.br/producao05/api/nacional"
SCHEMAS_EL = Path(__file__).resolve().parents[1] / "xml/schemas/el"


def dps_ausente(status, retorno):
    # A E&L retorna 400/EL99, em vez de 404, quando a DPS não está no repositório.
    # Aceite somente a mensagem específica; EL99 também pode acompanhar outras falhas.
    return (status == 400 and isinstance(retorno, dict) and len(retorno.get("erros", [])) == 1
            and retorno["erros"][0].get("codigo") == "EL99"
            and retorno["erros"][0].get("complemento") == "Chave informada para a DPS não existe no repositório municipal.")


def interpretar_retorno(status, retorno, id_dps, ambiente, *, consulta=False):
    if not isinstance(retorno, dict):
        return "INDETERMINADA_NAO_RETRANSMITIR"
    if retorno.get("erros"):
        return "REJEITADA"
    # GET por ID pode omitir idDPS enquanto processa. Um ID explicitamente
    # divergente nunca é aceito; XML disponível deve conter a própria DPS correta.
    id_compativel = retorno.get("idDPS") == id_dps or (consulta and "idDPS" not in retorno)
    if retorno.get("tipoAmbiente") != ambiente or not id_compativel:
        return "INDETERMINADA_NAO_RETRANSMITIR"
    if status not in (200, 201):
        return "INDETERMINADA_NAO_RETRANSMITIR"
    compactado = retorno.get("nfseXmlGZipB64", "")
    if not compactado or compactado in ("<em processamento no ambiente nacional>", "<em processamento adn nacional>"):
        return "EM_PROCESSAMENTO"
    try:
        dados = base64.b64decode(compactado, validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(dados)) as arquivo:
            xml = arquivo.read(5_000_001)
        if len(xml) > 5_000_000:
            return "INDETERMINADA_NAO_RETRANSMITIR"
        doc = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
        chave = retorno.get("chaveAcesso", "")
        if (doc.tag != f"{{{NS}}}NFSe" or not chave.isdigit() or len(chave) != 50
                or doc.find(f"{{{NS}}}infNFSe") is None
                or doc.find(f"{{{NS}}}infNFSe").get("Id") != f"NFS{chave}"
                or doc.findtext(f".//{{{NS}}}DPS/{{{NS}}}infDPS/{{{NS}}}tpAmb") != str(ambiente)
                or doc.find(f".//{{{NS}}}DPS/{{{NS}}}infDPS") is None
                or doc.find(f".//{{{NS}}}DPS/{{{NS}}}infDPS").get("Id") != id_dps):
            return "INDETERMINADA_NAO_RETRANSMITIR"
    except (ValueError, TypeError, OSError, EOFError, etree.XMLSyntaxError):
        return "INDETERMINADA_NAO_RETRANSMITIR"
    # XML disponível ainda exige validação fiscal e da assinatura do autorizador.
    return "XML_NFSE_DISPONIVEL_VALIDACAO_PENDENTE"


class ClienteMunicipalEL:
    def __init__(self, token, transporte=None):
        if not token or not token.strip():
            raise ValidationError("Configure o token de integração municipal.")
        self.token = token.strip()
        self.cliente = httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False,
                                    transport=transporte)

    def close(self):
        self.cliente.close()

    def _chamar(self, metodo, caminho, corpo=None):
        try:
            resposta = self.cliente.request(metodo, f"{BASE}/{caminho}", params={"token": self.token}, json=corpo)
        except httpx.HTTPError as erro:
            raise ValidationError(f"Falha de comunicação municipal ({type(erro).__name__}); não retransmita automaticamente.") from None
        try:
            retorno = resposta.json()
        except ValueError:
            retorno = {"resposta": resposta.text.replace(self.token, "[token removido]")[:2000]}

        def ocultar(valor):
            if isinstance(valor, str):
                return valor.replace(self.token, "[token removido]")
            if isinstance(valor, dict):
                return {chave: ocultar(item) for chave, item in valor.items()}
            if isinstance(valor, list):
                return [ocultar(item) for item in valor]
            return valor

        return resposta.status_code, ocultar(retorno)

    def consultar(self, id_dps, ambiente=2):
        if ambiente not in (1, 2) or len(id_dps) != 45 or not id_dps.startswith("DPS") or not id_dps[3:].isdigit():
            raise ValidationError("Ambiente ou identificador DPS inválido.")
        caminho = "homologacao/nfseDps" if ambiente == 2 else "nfseDps"
        return self._chamar("GET", f"{caminho}/{id_dps}")

    def enviar_homologacao(self, xml, a1):
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        doc = etree.fromstring(xml, parser)
        corpo = corpo_envio(xml)  # Bloqueia produção e qualquer valor diferente de R$ 1,00.
        if doc.findtext(f"{{{NS}}}infDPS/{{{NS}}}prest/{{{NS}}}CNPJ") != a1.cnpj:
            raise ValidationError("CNPJ da DPS diferente do certificado.")
        if not doc.findtext(f"{{{NS}}}infDPS/{{{NS}}}prest/{{{NS}}}IM"):
            raise ValidationError("Informe a inscrição municipal do prestador.")
        if not doc.findtext(f"{{{NS}}}infDPS/{{{NS}}}serv/{{{NS}}}cServ/{{{NS}}}cIntContrib"):
            raise ValidationError("Informe o código municipal em cIntContrib conforme o cadastro municipal.")
        schema = etree.XMLSchema(etree.parse(str(SCHEMAS_EL / "DPS_v1.01.xsd"), parser))
        if not schema.validate(doc):
            raise ValidationError([str(erro) for erro in schema.error_log])
        VerificadorSemPrefixo().verify(doc, x509_cert=a1.certificado.public_bytes(serialization.Encoding.PEM))
        identificador = doc.find(f"{{{NS}}}infDPS").get("Id")
        status, retorno = self.consultar(identificador)
        if not dps_ausente(status, retorno):
            raise ValidationError("A consulta prévia não confirmou ausência da DPS; envio bloqueado.")
        return self._chamar("POST", "homologacao/nfse", corpo)
