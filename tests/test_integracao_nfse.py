import base64
import gzip
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ObjectIdentifier
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from lxml import etree
from signxml.exceptions import InvalidDigest

from apps.fiscal.certificado import CertificadoA1
from apps.fiscal.services.homologacao import NS, VerificadorSemPrefixo, corpo_envio, preparar_dps
from apps.fiscal.services.municipal import consulta_rps, mensagens_resposta


@pytest.fixture
def arquivo_a1(tmp_path):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    titular = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CERTIFICADO SINTETICO")])
    agora = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(titular).issuer_name(titular)
            .public_key(chave.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"), b"\x0c\x0e12345678000195")]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .sign(chave, hashes.SHA256()))
    arquivo = tmp_path / "sintetico.pfx"
    arquivo.write_bytes(pkcs12.serialize_key_and_certificates(
        b"teste", chave, cert, None, serialization.BestAvailableEncryption(b"senha-teste")))
    return arquivo


def test_a1_senha_cnpj_e_tls(arquivo_a1):
    with pytest.raises(ValidationError):
        CertificadoA1(arquivo_a1, "errada")
    with pytest.raises(ValidationError):
        CertificadoA1(arquivo_a1, "senha-teste", "00000000000000")
    a1 = CertificadoA1(arquivo_a1, "senha-teste", "12345678000195")
    assert a1.contexto_tls().check_hostname
    assert "senha" not in a1.metadados()


def test_dps_assinada_serializada_xsd_e_adulteracao(arquivo_a1):
    a1 = CertificadoA1(arquivo_a1, "senha-teste")
    identificador, xml = preparar_dps(a1, 123)
    doc = etree.fromstring(xml)
    assert len(identificador) == 45
    assert all(no.prefix is None for no in doc.iter())
    assert gzip.decompress(base64.b64decode(corpo_envio(xml)["dpsXmlGZipB64"])) == xml
    doc.find(f"{{{NS}}}infDPS/{{{NS}}}valores/{{{NS}}}vServPrest/{{{NS}}}vServ").text = "2.00"
    with pytest.raises(InvalidDigest):
        VerificadorSemPrefixo().verify(doc, x509_cert=a1.certificado.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(ValidationError):
        corpo_envio(etree.tostring(doc))
    doc.find(f"{{{NS}}}infDPS/{{{NS}}}tpAmb").text = "1"
    with pytest.raises(ValidationError):
        corpo_envio(etree.tostring(doc))


def test_resposta_municipal_vazia_nao_e_sucesso():
    assert "não validada" in mensagens_resposta(b'<Envelope><Body><ConsultarNfsePorRpsResponse/></Body></Envelope>')[0]
    assert mensagens_resposta(b'<r><outputXML>&lt;r&gt;&lt;Codigo&gt;E1&lt;/Codigo&gt;&lt;Mensagem&gt;Recusada&lt;/Mensagem&gt;&lt;/r&gt;</outputXML></r>') == ["E1", "Recusada"]


def test_consulta_municipal_somente_leitura():
    xml = consulta_rps("12345678000195", 123, "89999")
    assert b"ConsultarNfsePorRps" in xml
    assert b"GerarNfse" not in xml
    with pytest.raises(ValidationError):
        consulta_rps("invalido", 123, "89999")


@pytest.mark.parametrize("cenario", ["ja_existe", "timeout"])
def test_envio_nao_retransmite_automaticamente(empresa, tmp_path, monkeypatch, cenario):
    from apps.fiscal.management.commands import testar_emissao_nfse as comando

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KSCENTRAL_A1_SENHA", "sintetica")
    monkeypatch.setattr(comando, "CertificadoA1", MagicMock())
    monkeypatch.setattr(comando, "preparar_dps", lambda *args: ("DPS_TESTE", b"xml-sintetico"))
    monkeypatch.setattr(comando, "corpo_envio", lambda xml: {"teste": True})
    cliente = MagicMock()
    cliente.get.return_value = httpx.Response(200 if cenario == "ja_existe" else 404)
    cliente.post.side_effect = httpx.ReadTimeout("timeout simulado")
    cliente.__enter__.return_value = cliente
    monkeypatch.setattr(comando.httpx, "Client", lambda **kwargs: cliente)
    with pytest.raises(CommandError):
        call_command("testar_emissao_nfse", "sintetico.pfx", enviar_homologacao=True)
    assert cliente.post.call_count == (0 if cenario == "ja_existe" else 1)
    resultado = (tmp_path / ".tools/emissoes-homologacao/DPS_TESTE/resultado.json").read_text(encoding="utf-8")
    assert ("NAO_ENVIADA_CONSULTA_PREVIA" if cenario == "ja_existe" else "INDETERMINADA_NAO_RETRANSMITIR") in resultado


def test_el_recebimento_nao_significa_autorizacao():
    from apps.fiscal.services.el_nacional import interpretar_retorno

    retorno = {"tipoAmbiente": 2, "idDPS": "DPS_TESTE", "nfseXmlGZipB64": "<em processamento no ambiente nacional>"}
    assert interpretar_retorno(201, retorno, "DPS_TESTE", 2) == "EM_PROCESSAMENTO"
    retorno["nfseXmlGZipB64"] = "<em processamento adn nacional>"
    assert interpretar_retorno(201, retorno, "DPS_TESTE", 2) == "EM_PROCESSAMENTO"
    retorno["erros"] = [{"Codigo": "E0037"}]
    assert interpretar_retorno(201, retorno, "DPS_TESTE", 2) == "REJEITADA"
    del retorno["erros"]
    retorno["tipoAmbiente"] = 1
    assert interpretar_retorno(201, retorno, "DPS_TESTE", 2) == "INDETERMINADA_NAO_RETRANSMITIR"


def test_el_consulta_processamento_sem_id_na_resposta():
    from apps.fiscal.services.el_nacional import interpretar_retorno

    retorno = {"tipoAmbiente": 1, "nfseXmlGZipB64": "<em processamento adn nacional>"}
    assert interpretar_retorno(200, retorno, "DPS_TESTE", 1, consulta=True) == "EM_PROCESSAMENTO"
    assert interpretar_retorno(201, retorno, "DPS_TESTE", 1) == "INDETERMINADA_NAO_RETRANSMITIR"
    retorno["idDPS"] = "OUTRA_DPS"
    assert interpretar_retorno(200, retorno, "DPS_TESTE", 1, consulta=True) == "INDETERMINADA_NAO_RETRANSMITIR"


def test_el_consulta_token_sem_exposicao_em_timeout():
    from apps.fiscal.services.el_nacional import ClienteMunicipalEL

    def falhar(request):
        assert request.url.host == "ba-valenca-pm-nfs-backend.cloud.el.com.br"
        assert request.url.params["token"] == "segredo-sintetico"
        assert request.method == "GET"
        raise httpx.ReadTimeout(f"URL com segredo: {request.url}")

    cliente = ClienteMunicipalEL("segredo-sintetico", httpx.MockTransport(falhar))
    try:
        with pytest.raises(ValidationError) as erro:
            cliente.consultar("DPS293290326250128100011389999020261009021101")
        assert "segredo-sintetico" not in str(erro.value)
    finally:
        cliente.close()


def test_el_envio_bloqueia_producao_e_campos_municipais_ausentes(arquivo_a1):
    from apps.fiscal.services.el_nacional import ClienteMunicipalEL

    a1 = CertificadoA1(arquivo_a1, "senha-teste")
    _, xml = preparar_dps(a1, 123)
    requisicoes = []
    cliente = ClienteMunicipalEL("sintetico", httpx.MockTransport(lambda req: requisicoes.append(req)))
    try:
        with pytest.raises(ValidationError, match="inscrição municipal"):
            cliente.enviar_homologacao(xml, a1)
        with pytest.raises(ValidationError, match="exclusivamente produção restrita"):
            cliente.enviar_homologacao(xml.replace(b"<tpAmb>2", b"<tpAmb>1"), a1)
        assert not requisicoes
    finally:
        cliente.close()


@pytest.mark.parametrize("ausente", [True, False])
def test_el_consulta_ausencia_sem_confundir_erro_generico(arquivo_a1, ausente):
    from apps.fiscal.services.el_nacional import SCHEMAS_EL, ClienteMunicipalEL

    a1 = CertificadoA1(arquivo_a1, "senha-teste")
    identificador, xml = preparar_dps(a1, 123, inscricao_municipal="16845",
                                     codigo_municipal="101", codigo_nacional="010101", nbs="115021000",
                                     schemas=SCHEMAS_EL, aliquota_iss_teste="2.00")
    requisicoes = []

    def responder(req):
        requisicoes.append(req)
        if req.method == "GET":
            return httpx.Response(400, json={"erros": [{"codigo": "EL99", "complemento":
                "Chave informada para a DPS não existe no repositório municipal." if ausente else "Token inválido."}]})
        return httpx.Response(201, json={"tipoAmbiente": 2, "idDPS": identificador,
                                       "nfseXmlGZipB64": "<em processamento adn nacional>"})

    cliente = ClienteMunicipalEL("sintetico", httpx.MockTransport(responder))
    try:
        if ausente:
            assert cliente.enviar_homologacao(xml, a1)[0] == 201
            assert [req.method for req in requisicoes] == ["GET", "POST"]
        else:
            with pytest.raises(ValidationError, match="envio bloqueado"):
                cliente.enviar_homologacao(xml, a1)
            assert [req.method for req in requisicoes] == ["GET"]
    finally:
        cliente.close()


def test_producao_valores_explicitos_assinatura_e_separacao_homologacao(arquivo_a1):
    from apps.fiscal.services.el_nacional import SCHEMAS_EL
    from apps.fiscal.services.producao import corpo_producao, preparar_dps_producao

    a1 = CertificadoA1(arquivo_a1, "senha-teste")
    parametros = dict(municipio="2932903", inscricao_municipal="16845",
                      tomador={"cpf": "52998224725", "nome": "TOMADOR SINTETICO"},
                      codigo_nacional="010101", nbs="115022000", codigo_municipal="101",
                      descricao="Desenvolvimento de sistema sob medida", valor="1.00",
                      aliquota_iss="2.00", total_tributos_simples="6.00")
    identificador, xml = preparar_dps_producao(a1, 123, **parametros)
    assert len(identificador) == 45
    assert b"<tpAmb>1</tpAmb>" in xml and b"<pTotTribSN>6.00</pTotTribSN>" in xml
    assert b"HOMOLOGACAO" not in xml
    assert gzip.decompress(base64.b64decode(corpo_producao(xml, a1, SCHEMAS_EL)["dpsXmlGZipB64"])) == xml
    with pytest.raises(ValidationError):
        corpo_envio(xml)
    with pytest.raises(InvalidDigest):
        corpo_producao(xml.replace(b"<pTotTribSN>6.00", b"<pTotTribSN>7.00"), a1)
    parametros["total_tributos_simples"] = None
    with pytest.raises(ValidationError):
        preparar_dps_producao(a1, 124, **parametros)


@pytest.mark.parametrize("valor", ["NaN", "Infinity", "-1", "101", "6.001"])
def test_producao_bloqueia_percentual_invalido(valor):
    from decimal import Decimal

    from apps.fiscal.services.producao import decimal_fiscal

    with pytest.raises(ValidationError):
        decimal_fiscal(valor, Decimal("0"), Decimal("100"))
