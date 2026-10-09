import httpx
import pytest
import respx
from django.test import override_settings
from django.urls import reverse

from apps.cadastros.models import Pessoa
from apps.core.models import Anexo, LogIntegracao, Parametro, Segredo
from apps.core.services.integracao import mascarar
from apps.core.templatetags.ks import brl, competencia
from apps.core.validadores import cnpj_valido, cpf_valido, formatar_doc


def test_validadores_documentos():
    assert cnpj_valido("62.501.281/0001-13")
    assert not cnpj_valido("62.501.281/0001-14")
    assert cpf_valido("529.982.247-25")
    assert not cpf_valido("111.111.111-11")
    assert formatar_doc("62501281000113") == "62.501.281/0001-13"


def test_formatacao_brasileira():
    from datetime import date
    from decimal import Decimal

    assert brl(Decimal("1234.56")) == "R$ 1.234,56"
    assert brl(Decimal("-10")) == "−R$ 10,00"
    assert competencia(date(2026, 10, 1)) == "10/2026"


def test_segredo_criptografado(empresa):
    s = Segredo.criar("senha_pfx", "minha-senha", escopo="FISCAL")
    s.refresh_from_db()
    assert b"minha-senha" not in bytes(s.valor_criptografado)
    assert s.ler() == "minha-senha"


def test_mascarar_segredos():
    t = mascarar('{"login": "ks", "senha": "123456", "token": "abc"} Authorization: Bearer xyz.abc')
    assert "123456" not in t and "abc" not in t.split("Bearer")[1]


def test_parametro_padrao(empresa):
    assert Parametro.get("certidoes.dias_alerta") == [30, 15, 7, 0]
    assert Parametro.get("inexistente", 42) == 42


def test_modelo_base_preenche_empresa_e_uuid7(empresa):
    p = Pessoa.objects.create(cpf_cnpj="62501281000113", razao_social="KS TEC")
    assert p.empresa == empresa
    assert p.pk.version == 7
    assert p.history.count() == 1


def test_anexo_hash_e_retencao(empresa, pessoa):
    from django.core.exceptions import PermissionDenied

    a = Anexo.criar(pessoa, "nota.xml", b"<xml/>", retencao_anos=5)
    assert a.tamanho == 6 and len(a.hash_sha256) == 64
    with pytest.raises(PermissionDenied):
        a.delete()


@pytest.mark.django_db
def test_login_por_email(client, admin_user):
    r = client.post(reverse("core:login"), {"username": "ADMIN@kstec.online", "password": "Senha-forte-123"})
    assert r.status_code == 302


@override_settings(MFA_OBRIGATORIO=True)
def test_mfa_obrigatorio_para_admin(client, admin_user):
    client.force_login(admin_user)
    r = client.get(reverse("painel:home"))
    assert r.status_code == 302 and reverse("core:mfa_configurar") in r["Location"]


@override_settings(MFA_OBRIGATORIO=True)
def test_mfa_nao_exigido_para_leitura(client, leitor):
    client.force_login(leitor)
    assert client.get(reverse("painel:home")).status_code == 200


def test_paginas_principais_renderizam(cli, pessoa):
    for nome in ["painel:home", "cadastros:pessoa_lista", "cadastros:pessoa_nova", "core:componentes",
                 "core:configuracoes", "core:empresa", "core:usuario_lista", "core:parametro_lista",
                 "core:log_lista", "core:notificacoes", "core:perfil", "cadastros:contato_lista"]:
        r = cli.get(reverse(nome))
        assert r.status_code == 200, nome
    r = cli.get(reverse("cadastros:pessoa_detalhe", args=[pessoa.pk]))
    assert r.status_code == 200 and "13.927.819/0001-40" in r.content.decode()
    assert "Content-Security-Policy" in r


def test_criar_pessoa_com_endereco(cli, empresa):
    r = cli.post(reverse("cadastros:pessoa_nova"), {
        "cpf_cnpj": "62.501.281/0001-13", "razao_social": "KS TEC", "eh_cliente": "on",
        "cep": "45400-000", "logradouro": "Rua A", "numero": "1", "bairro": "Centro",
        "municipio_ibge": "2932903", "municipio_nome": "Valença", "uf": "ba",
    })
    assert r.status_code == 302
    p = Pessoa.objects.get(cpf_cnpj="62501281000113")
    assert p.endereco.uf == "BA" and p.endereco.cep == "45400000"


def test_cnpj_invalido_recusado(cli, empresa):
    r = cli.post(reverse("cadastros:pessoa_nova"), {"cpf_cnpj": "11.111.111/1111-11", "razao_social": "X"})
    assert r.status_code == 200 and not Pessoa.objects.exists()


def test_leitura_nao_escreve(client, leitor):
    client.force_login(leitor)
    assert client.get(reverse("cadastros:pessoa_lista")).status_code == 200
    r = client.post(reverse("cadastros:pessoa_nova"), {"cpf_cnpj": "62501281000113", "razao_social": "X"})
    assert r.status_code == 403


@respx.mock
def test_consulta_cnpj_brasilapi(cli):
    respx.get("https://brasilapi.com.br/api/cnpj/v1/62501281000113").mock(return_value=httpx.Response(200, json={
        "razao_social": "KS TEC SOLUCOES DE TECNOLOGIA LTDA", "nome_fantasia": "KS TEC", "cep": "45400000",
        "logradouro": "RUA X", "numero": "10", "bairro": "CENTRO", "municipio": "VALENCA", "uf": "BA",
        "codigo_municipio_ibge": 2932903, "opcao_pelo_simples": True, "descricao_situacao_cadastral": "ATIVA",
    }))
    r = cli.get(reverse("core:consulta_cnpj") + "?cnpj=62.501.281/0001-13")
    d = r.json()
    assert d["razao_social"].startswith("KS TEC") and d["endereco"]["municipio_ibge"] == "2932903"
    assert LogIntegracao.objects.filter(servico="BRASILAPI", sucesso=True).exists()


def test_busca_global(cli, pessoa):
    r = cli.get(reverse("core:busca") + "?q=valen")
    assert "MUNICIPIO DE VALENCA" in r.content.decode()


def test_lista_htmx_parcial(cli, pessoa):
    r = cli.get(reverse("cadastros:pessoa_lista") + "?q=valen&parcial=1", HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert "tabela-dados" in html and "<html" not in html
