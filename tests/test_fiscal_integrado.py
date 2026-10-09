import base64
import gzip
from copy import deepcopy
from datetime import date
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from django.urls import reverse
from lxml import etree
from signxml import methods

from apps.cadastros.models import Pessoa
from apps.catalogo.models import ItemCatalogo, ServicoMunicipal
from apps.catalogo.municipal import importar_municipais
from apps.catalogo.seeds import seed
from apps.financeiro.models import ContaBancaria, Lancamento
from apps.financeiro.services.conciliacao import conciliar, importar_extrato
from apps.financeiro.services.recebiveis import gerar_recebivel
from apps.fiscal.models import ConfiguracaoFiscal, NotaFiscal, PerfilFiscal
from apps.fiscal.services import emissao
from apps.fiscal.services.configuracao import cadastrar_certificado, carregar_a1, salvar_configuracao
from apps.fiscal.services.el_nacional import ClienteMunicipalEL
from apps.fiscal.services.homologacao import NS, AssinadorSemPrefixo, elemento
from apps.fiscal.services.rascunhos import salvar
from tests.test_integracao_nfse import arquivo_a1 as fixture_a1

arquivo_a1 = fixture_a1


@pytest.fixture
def preparado(empresa, arquivo_a1, settings, tmp_path):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.MEDIA_ROOT = tmp_path
    empresa.cnpj = "12345678000195"
    empresa.inscricao_municipal = "16845"
    empresa.save()
    seed(empresa)
    item = ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-DEV")
    item.codigo_tributacao_municipal = "101"
    item.save()
    ServicoMunicipal.objects.create(municipio_ibge="2932903", item_lc116="01.01", codigo_integracao="101",
                 codigo_confirmado=True, descricao="Análise e desenvolvimento de sistemas", fonte="https://prefeitura.example/servicos")
    perfil = PerfilFiscal.objects.create(empresa=empresa, nome="Sem retenção", aliquota_iss=Decimal("2"))
    cert = cadastrar_certificado(empresa, arquivo_a1.read_bytes(), "senha-teste")
    config = ConfiguracaoFiscal(empresa=empresa, certificado=cert, perfil_padrao=perfil,
                ambiente=1, aliquota_iss=Decimal("2"), total_tributos_simples=Decimal("6"),
                vigencia_inicio=date(2026, 1, 1), vigencia_fim=date(2027, 12, 31), fonte_tributacao="Massa sintética de testes")
    salvar_configuracao(config, token="token-sintetico")
    pessoa = Pessoa.objects.create(empresa=empresa, cpf_cnpj="52998224725", tipo="F", razao_social="TOMADOR SINTETICO")
    nota = NotaFiscal(empresa=empresa, tomador=pessoa, perfil=perfil, item_catalogo=item,
        competencia=date(2026, 10, 1), discriminacao="Desenvolvimento de sistema sob medida", valor_servicos=Decimal("1"),
        aliquota_iss=Decimal("2"))
    salvar(nota)
    return nota, config


def resposta_nfse(tentativa, a1):
    chave = "1" * 50
    raiz = etree.Element(f"{{{NS}}}NFSe", nsmap={None: NS}, versao="1.01")
    inf = elemento(raiz, "infNFSe")
    inf.set("Id", "NFS" + chave)
    for tag, valor in [("xLocEmi", "Valença"), ("xLocPrestacao", "Valença"), ("nNFSe", "123"),
                       ("xTribNac", "Análise e desenvolvimento de sistemas"), ("verAplic", "TESTE_1"),
                       ("ambGer", "1"), ("tpEmis", "1"), ("cStat", "100"),
                       ("dhProc", "2026-10-09T01:00:00-03:00"), ("nDFSe", "123")]:
        elemento(inf, tag, valor)
    emit = elemento(inf, "emit")
    elemento(emit, "CNPJ", a1.cnpj)
    elemento(emit, "xNome", "EMITENTE SINTETICO")
    end = elemento(emit, "enderNac")
    for tag, valor in [("xLgr", "Rua de Teste"), ("nro", "1"), ("xBairro", "Centro"),
                       ("cMun", "2932903"), ("UF", "BA"), ("CEP", "45400000")]:
        elemento(end, tag, valor)
    elemento(elemento(inf, "valores"), "vLiq", "1.00")
    dps = etree.fromstring(tentativa.dps_assinada.ler())
    for sig in dps.findall("{http://www.w3.org/2000/09/xmldsig#}Signature"):
        dps.remove(sig)
    inf.append(deepcopy(dps))
    signer = AssinadorSemPrefixo(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                                 c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    signer.namespaces = {None: "http://www.w3.org/2000/09/xmldsig#"}
    assinado = signer.sign(raiz, key=a1.chave, cert=a1.certificado.public_bytes(serialization.Encoding.PEM),
                           reference_uri="#NFS" + chave)
    xml = etree.tostring(assinado)
    return {"tipoAmbiente": tentativa.ambiente, "idDPS": tentativa.id_dps, "chaveAcesso": chave,
            "nfseXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode()}


def test_certificado_cifrado_e_historico_sem_credenciais(preparado, arquivo_a1):
    _, config = preparado
    assert arquivo_a1.read_bytes() != bytes(config.certificado.arquivo_criptografado)
    assert b"senha-teste" not in bytes(config.certificado.senha_criptografada)
    assert carregar_a1(config).cnpj == config.empresa.cnpj
    assert "arquivo_criptografado" not in {f.name for f in config.certificado.history.model._meta.fields}
    assert config.token_municipal.ler() == "token-sintetico"


def test_preparacao_numeracao_e_bloqueio_de_repeticao(preparado):
    nota, config = preparado
    tentativa, _ = emissao.preparar_tentativa(nota, config)
    nota.refresh_from_db()
    assert nota.status == "TRANSMITINDO" and len(nota.id_dps) == 45
    assert tentativa.hash_requisicao and tentativa.dps_assinada.ler()
    with pytest.raises(ValidationError):
        emissao.preparar_tentativa(nota, config)
    assert nota.tentativas.count() == 1


def test_autorizacao_recebivel_unico_e_conciliacao(preparado):
    nota, config = preparado
    tentativa, a1 = emissao.preparar_tentativa(nota, config)
    retorno = resposta_nfse(tentativa, a1)
    autorizada = emissao.registrar_resultado(tentativa, 200, retorno, consulta=True)
    assert autorizada.status == "AUTORIZADA" and autorizada.numero_nfse == "123"
    recebivel = gerar_recebivel(autorizada)
    assert gerar_recebivel(autorizada).pk == recebivel.pk
    assert recebivel.valor == Decimal("1") and recebivel.conta_bancaria is None
    emissao.registrar_resultado(tentativa, 200, retorno, consulta=True)
    assert Lancamento.objects.filter(nota_fiscal=nota).count() == 1
    conta = ContaBancaria.objects.create(empresa=nota.empresa, nome="Conta sintética")
    extrato = b"id;data;valor;descricao\nFIT001;2026-10-01;1,00;Recebimento sinteticamente comprovado\n"
    assert importar_extrato(nota.empresa, conta, extrato, "extrato.csv") == (1, 0)
    assert importar_extrato(nota.empresa, conta, extrato, "extrato.csv") == (0, 1)
    transacao = conta.transacoes.get()
    pago = conciliar(transacao, recebivel)
    assert pago.status == "PAGO" and pago.conciliado and pago.conta_bancaria == conta
    assert pago.data_pagamento == date(2026, 10, 1)
    with pytest.raises(ValidationError):
        conciliar(transacao, recebivel)


def test_xml_adulterado_nao_autoriza(preparado):
    nota, config = preparado
    tentativa, a1 = emissao.preparar_tentativa(nota, config)
    retorno = resposta_nfse(tentativa, a1)
    xml = gzip.decompress(base64.b64decode(retorno["nfseXmlGZipB64"]))
    retorno["nfseXmlGZipB64"] = base64.b64encode(gzip.compress(xml.replace(b"<vLiq>1.00", b"<vLiq>2.00"))).decode()
    with pytest.raises(ValidationError):
        emissao.registrar_resultado(tentativa, 200, retorno, consulta=True)
    nota.refresh_from_db()
    assert nota.status != "AUTORIZADA" and not Lancamento.objects.filter(nota_fiscal=nota).exists()


def test_autorizacao_preservada_se_financeiro_incompleto(preparado):
    from apps.financeiro.models import CategoriaFinanceira

    nota, config = preparado
    CategoriaFinanceira.objects.create(empresa=nota.empresa, nome="Vendas avulsas", tipo="RECEITA",
                                       grupo_dre="RECEITA_BRUTA", ativo=False)
    tentativa, a1 = emissao.preparar_tentativa(nota, config)
    autorizada = emissao.registrar_resultado(tentativa, 200, resposta_nfse(tentativa, a1), consulta=True)
    assert autorizada.status == "AUTORIZADA" and autorizada.xml_autorizado_id
    assert autorizada.emissao_snapshot["recebivel_pendente"]
    assert not Lancamento.objects.filter(nota_fiscal=nota).exists()
    CategoriaFinanceira.objects.filter(empresa=nota.empresa, nome="Vendas avulsas").update(ativo=True)
    gerar_recebivel(autorizada)
    autorizada.refresh_from_db()
    assert "recebivel_pendente" not in autorizada.emissao_snapshot


def test_timeout_bloqueia_segundo_post(preparado, monkeypatch):
    nota, config = preparado
    chamadas = []
    def responder(req):
        chamadas.append(req.method)
        if req.method == "GET":
            return httpx.Response(400, json={"tipoAmbiente": 1, "erros": [{"codigo": "EL99", "complemento":
                         "Chave informada para a DPS não existe no repositório municipal."}]})
        raise httpx.ReadTimeout("erro sintético")
    monkeypatch.setattr(emissao, "ClienteMunicipalEL", lambda token: ClienteMunicipalEL(token, httpx.MockTransport(responder)))
    with pytest.raises(ValidationError):
        emissao.transmitir(nota)
    nota.refresh_from_db()
    assert nota.status == "ERRO_COMUNICACAO"
    with pytest.raises(ValidationError):
        emissao.transmitir(nota)
    assert chamadas == ["GET", "POST"]


def test_configuracao_expirada_e_codigo_nao_confirmado_bloqueiam(preparado):
    nota, config = preparado
    config.vigencia_fim = date(2026, 9, 30)
    with pytest.raises(ValidationError):
        emissao.validar_emissao(nota, config)
    config.vigencia_fim = date(2027, 12, 31)
    ServicoMunicipal.objects.update(codigo_confirmado=False)
    with pytest.raises(ValidationError, match="código municipal"):
        emissao.validar_emissao(nota, config)


def test_municipal_importacao_preserva_confirmado_e_rejeita_repetido(db):
    fonte = "https://prefeitura.example/lista"
    dados = b"item_lc116;descricao;codigo_integracao\n01.01;Desenvolvimento;101\n"
    assert importar_municipais(dados, "servicos.csv", "2932903", fonte, True) == 1
    assert importar_municipais(dados.replace(b";101", b";"), "servicos.csv", "2932903", fonte) == 1
    obj = ServicoMunicipal.objects.get()
    assert obj.codigo_confirmado and obj.codigo_integracao == "101"
    with pytest.raises(ValidationError):
        importar_municipais(dados + b"01.01;Duplicado;102\n", "s.csv", "2932903", fonte)
    obj.refresh_from_db()
    assert obj.codigo_integracao == "101"


def test_configuracao_e_nota_na_interface_sem_segredos(preparado, cli):
    nota, _ = preparado
    r = cli.get(reverse("fiscal:configuracao"))
    assert r.status_code == 200 and b"token-sintetico" not in r.content and b"senha-teste" not in r.content
    assert cli.get(reverse("fiscal:nota_detalhe", args=[nota.pk])).status_code == 200
    assert cli.get(reverse("fiscal:emitir", args=[nota.pk])).status_code == 200
    assert cli.get(reverse("catalogo:tabelas")).status_code == 200
    assert cli.get(reverse("catalogo:municipal_lista")).status_code == 200
    assert cli.get(reverse("financeiro:extratos")).status_code == 200


def test_leitura_nao_emite_nem_muda_configuracao(preparado, leitor, client):
    nota, _ = preparado
    client.force_login(leitor)
    assert client.post(reverse("fiscal:configuracao"), {}).status_code == 403
    assert client.post(reverse("fiscal:emitir", args=[nota.pk]), {"confirmar": "on"}).status_code == 403
    assert not nota.tentativas.exists()


def test_importacao_ofx_e_divergencia_id_bancario(empresa):
    conta = ContaBancaria.objects.create(empresa=empresa, nome="Banco teste")
    ofx = b"<OFX><BANKTRANLIST><STMTTRN><DTPOSTED>20261001000000[-3:BRT]\n<TRNAMT>-10.00\n<FITID>ABC\n<MEMO>Debito teste\n</STMTTRN></BANKTRANLIST></OFX>"
    assert importar_extrato(empresa, conta, ofx, "banco.ofx") == (1, 0)
    assert conta.transacoes.get().valor == Decimal("-10")
    with pytest.raises(ValidationError):
        importar_extrato(empresa, conta, ofx.replace(b"-10.00", b"-11.00"), "banco.ofx")
    assert conta.transacoes.get().valor == Decimal("-10")


def test_importacao_confirmada_sem_retransmissao_e_sem_duplicar(preparado):
    from apps.fiscal.services.importacao import importar_confirmada

    nota, config = preparado
    tentativa, a1 = emissao.preparar_tentativa(nota, config)
    retorno = resposta_nfse(tentativa, a1)
    xml = gzip.decompress(base64.b64decode(retorno["nfseXmlGZipB64"]))
    # O documento recuperado existe no provedor antes de existir como autorizado no banco.
    tentativa.delete()
    nota.delete()
    importada, nova = importar_confirmada(config.empresa, xml, retorno, "MUNICIPAL_EL")
    assert nova and importada.status == "AUTORIZADA"
    assert importada.tentativas.get().situacao == "IMPORTADA_AUTORIZADA"
    assert Lancamento.objects.filter(nota_fiscal=importada).count() == 1
    repetida, nova = importar_confirmada(config.empresa, xml, retorno, "MUNICIPAL_EL")
    assert not nova and repetida.pk == importada.pk
    assert Lancamento.objects.filter(nota_fiscal=importada).count() == 1
    with pytest.raises(ValidationError, match="difere"):
        importar_confirmada(config.empresa, xml.replace(b"<vLiq>1.00", b"<vLiq>2.00"), retorno, "MUNICIPAL_EL")


def test_cadastros_alterados_e_resposta_invalida(preparado):
    nota, config = preparado
    nota.tomador.razao_social = "Nome alterado após revisão"
    nota.tomador.save()
    with pytest.raises(ValidationError, match="tomador mudou"):
        emissao.validar_emissao(nota, config)
    salvar(nota)
    tentativa, _ = emissao.preparar_tentativa(nota, config)
    resultado = emissao.registrar_resultado(tentativa, 502, ["resposta inesperada"])
    assert resultado.status == "ERRO_COMUNICACAO"
    assert not Lancamento.objects.filter(nota_fiscal=nota).exists()


def test_configuracao_sem_substituir_segredos_e_municipal_vazio(preparado):
    _, config = preparado
    certificado_id, token_id = config.certificado_id, config.token_municipal_id
    salvar_configuracao(config, token="")
    assert config.certificado_id == certificado_id and config.token_municipal_id == token_id
    obj = ServicoMunicipal.objects.get()
    obj.codigo_integracao = ""
    with pytest.raises(ValidationError):
        obj.full_clean()
    with pytest.raises(ValidationError, match="vazio"):
        importar_municipais(b"", "vazio.csv", "2932903", "https://prefeitura.example/lista")


def test_consulta_indisponivel_preserva_tentativa_na_interface(preparado, cli, monkeypatch):
    nota, config = preparado
    emissao.preparar_tentativa(nota, config)
    def indisponivel(obj):
        raise httpx.ReadTimeout("Falha sintética")
    monkeypatch.setattr(emissao, "consultar", indisponivel)
    resposta = cli.post(reverse("fiscal:consultar", args=[nota.pk]), follow=True)
    assert resposta.status_code == 200 and "Consulta indisponível" in resposta.content.decode()
    nota.refresh_from_db()
    assert nota.status == "TRANSMITINDO" and nota.tentativas.count() == 1


def test_classificacao_nacional_incoerente_bloqueia_preparacao(preparado):
    nota, config = preparado
    nota.item_catalogo.codigo_tributacao_nacional.item = "02"
    with pytest.raises(ValidationError, match="corresponder"):
        emissao.validar_emissao(nota, config)
    assert not nota.tentativas.exists()


def test_importacao_historica_preserva_valores_do_xml(preparado):
    from apps.fiscal.models import SequenciaNumeracao, TentativaTransmissao
    from apps.fiscal.services.importacao import importar_historica

    nota, config = preparado
    tentativa, a1 = emissao.preparar_tentativa(nota, config)
    xml = gzip.decompress(base64.b64decode(resposta_nfse(tentativa, a1)["nfseXmlGZipB64"]))
    antes = SequenciaNumeracao.objects.get().ultimo_numero
    TentativaTransmissao.objects.filter(nota=nota).delete()
    importada, criada = importar_historica(config.empresa, xml, gerar_receber=False)
    assert criada and importada.pk != nota.pk and importada.status == "AUTORIZADA"
    assert importada.numero_nfse == "123" and importada.valor_liquido == Decimal("1.00")
    assert importada.tentativas.get().situacao == "IMPORTADA_AUTORIZADA"
    assert importar_historica(config.empresa, xml)[1] is False
    assert importar_historica(config.empresa, xml, cancelada=True)[0].status == "CANCELADA"
    assert SequenciaNumeracao.objects.get().ultimo_numero == antes
    config.empresa.cnpj = "11222333000181"
    with pytest.raises(ValidationError):
        importar_historica(config.empresa, xml)


def test_dps_iss_retido_espelha_nota_autorizada_do_portal(preparado):
    """Mesmos campos da NFS-e 2600000000007 (válida): regApTribSN=2, tpRetISSQN=2, sem pAliq, tomador com IM e endereço."""
    from apps.core.models import Endereco

    nota, config = preparado
    tomador = nota.tomador
    tomador.endereco = Endereco.objects.create(cep="45400000", logradouro="General Labatut", numero="S/N", bairro="Centro",
                                               municipio_ibge="2932903", municipio_nome="Valença", uf="BA")
    tomador.inscricao_municipal = "0000005082"
    tomador.save()
    nota.perfil.iss_retido = True
    nota.perfil.save()
    nota.valor_servicos = Decimal("4950")
    salvar(nota)
    assert (nota.valor_iss, nota.valor_iss_retido, nota.valor_liquido) == (Decimal("99.00"), Decimal("99.00"), Decimal("4851.00"))
    emissao.validar_emissao(nota, config)
    tentativa, _ = emissao.preparar_tentativa(nota, config)
    dps = etree.fromstring(tentativa.dps_assinada.ler()).find(f"{{{NS}}}infDPS")
    t = lambda c: dps.findtext("/".join(f"{{{NS}}}{x}" for x in c.split("/")))  # noqa: E731
    assert t("prest/regTrib/regApTribSN") == "2" and t("valores/trib/tribMun/tpRetISSQN") == "2"
    assert dps.find(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}tribMun/{{{NS}}}pAliq") is None
    assert t("toma/IM") == "0000005082" and t("toma/end/endNac/cMun") == "2932903" and t("toma/end/xBairro") == "Centro"


def test_iss_retido_exige_tomador_local(preparado):
    nota, config = preparado
    nota.perfil.iss_retido = True
    nota.perfil.save()
    salvar(nota)
    with pytest.raises(ValidationError, match="município do emitente"):
        emissao.validar_emissao(nota, config)


def test_quebras_de_linha_normalizadas_como_no_emissor(preparado):
    """O E&L autoriza com as quebras de linha da discriminação trocadas por espaço (NFS-e 2600000000013)."""
    from apps.fiscal.services.documentos import conteudo

    nota, config = preparado
    nota.discriminacao = "Serviço mensal.\n\nChave PIX: 62501281000113"
    salvar(nota)
    tentativa, _ = emissao.preparar_tentativa(nota, config)
    dps = etree.fromstring(tentativa.dps_assinada.ler())
    assert dps.find(f".//{{{NS}}}xDescServ").text == "Serviço mensal. Chave PIX: 62501281000113"
    a = etree.fromstring(b"<x><d>A\n\nB</d></x>")
    b = etree.fromstring(b"<x><d>A B</d></x>")
    assert conteudo(a) == conteudo(b)
