from datetime import date

import httpx
import pytest
import respx
from django.urls import reverse

from apps.cadastros.models import Pessoa
from apps.core.services.brasilapi import ConsultaIndisponivel, consultar_cnpj

URL = "https://brasilapi.com.br/api/cnpj/v1/62501281000113"


@pytest.mark.parametrize("simples", [True, False, None])
@respx.mock
def test_dados_ampliados_e_simples(cli, simples):
    respx.get(URL).mock(return_value=httpx.Response(200, json={
        "razao_social": "KS TEC SOLUCOES DE TECNOLOGIA LTDA", "nome_fantasia": "KS TEC",
        "opcao_pelo_simples": simples, "cnae_fiscal": 6201501,
        "cnae_fiscal_descricao": "Desenvolvimento de programas de computador",
        "natureza_juridica": "Sociedade Empresária Limitada", "porte": "MICRO EMPRESA",
        "data_inicio_atividade": "2025-09-01", "descricao_situacao_cadastral": "ATIVA",
        "email": "CONTATO@KSTEC.ONLINE", "ddd_telefone_1": "73999990000",
        "logradouro": "Rua de teste", "numero": "10", "municipio": "VALENCA", "uf": "BA",
        "cep": "45400000", "codigo_municipio_ibge": 2932903,
    }))
    r = cli.get(reverse("core:consulta_cnpj"), {"cnpj": "62.501.281/0001-13"})
    dados = r.json()
    assert dados["optante_simples"] is simples
    assert dados["cnae_principal"] == "6201501"
    assert dados["data_abertura"] == "2025-09-01"
    assert dados["situacao_cadastral"] == "ATIVA"
    dados.update(dados.pop("endereco"))
    dados["eh_cliente"] = "on"
    dados["optante_simples"] = "unknown" if simples is None else str(simples).lower()
    r = cli.post(reverse("cadastros:pessoa_nova"), dados)
    assert r.status_code == 302, r.context["form"].errors if r.status_code == 200 else r.status_code
    pessoa = Pessoa.objects.get(cpf_cnpj="62501281000113")
    assert pessoa.razao_social.startswith("KS TEC")
    assert pessoa.natureza_juridica == "Sociedade Empresária Limitada"
    assert pessoa.cnae_principal == "6201501"
    assert pessoa.data_abertura == date(2025, 9, 1)
    assert pessoa.email == "contato@kstec.online"
    assert pessoa.endereco.municipio_ibge == "2932903"
    assert pessoa.optante_simples is simples


@pytest.mark.parametrize("status", [404, 429, 500, 503])
@respx.mock
def test_indisponibilidade_preserva_cadastro(cli, status):
    respx.get(URL).mock(return_value=httpx.Response(status, json={"message": "Indisponível"}))
    r = cli.get(reverse("core:consulta_cnpj"), {"cnpj": "62501281000113"})
    assert "erro" in r.json()
    assert not Pessoa.objects.exists()


@respx.mock
def test_timeout_tratado(cli):
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("timeout"))
    r = cli.get(reverse("core:consulta_cnpj"), {"cnpj": "62501281000113"})
    assert "indisponível" in r.json()["erro"]


@pytest.mark.parametrize("resposta", [httpx.Response(200, text="não é JSON"),
    httpx.Response(200, json=[]), httpx.Response(200, json={})])
@respx.mock
def test_resposta_invalida_tratada(cli, resposta):
    respx.get(URL).mock(return_value=resposta)
    assert "erro" in cli.get(reverse("core:consulta_cnpj"), {"cnpj": "62501281000113"}).json()


@respx.mock
def test_documento_invalido_sem_chamada_externa():
    with pytest.raises(ConsultaIndisponivel, match="CNPJ válido"):
        consultar_cnpj("11111111111111")
    assert not respx.calls


def test_empresa_com_consulta_disponivel(cli):
    r = cli.get(reverse("core:empresa"))
    assert r.status_code == 200
    assert 'data-consulta-cnpj' in r.content.decode()
    assert 'data-buscar-cnpj' in r.content.decode()
