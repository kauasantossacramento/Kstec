from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.catalogo.models import ItemCatalogo
from apps.catalogo.seeds import seed
from apps.fiscal.models import NotaFiscal, PerfilFiscal
from apps.fiscal.services.calculo import calcular
from apps.fiscal.services.rascunhos import salvar


@pytest.fixture
def nota(empresa, pessoa):
    seed(empresa)
    empresa.optante_simples = False
    perfil = PerfilFiscal.objects.create(nome="ISS 5%", aliquota_iss=Decimal("5"))
    return NotaFiscal(empresa=empresa, tomador=pessoa,
                      item_catalogo=ItemCatalogo.objects.get(codigo_interno="TI-SUP"), perfil=perfil,
                      competencia=date(2026, 10, 1), discriminacao="Suporte técnico mensal",
                      valor_servicos=Decimal("1232.25"))


def test_iss_normal_e_auditoria(nota):
    salvar(nota)
    nota.refresh_from_db()
    assert nota.base_calculo == Decimal("1232.25")
    assert nota.valor_iss == Decimal("61.61")
    assert nota.valor_liquido == Decimal("1232.25")
    assert nota.valor_iss_retido == 0
    assert nota.history.count() == 1


def test_snapshot_preserva_dados_apos_mudanca_cadastro(nota):
    salvar(nota)
    nome = nota.tomador.razao_social
    nota.tomador.razao_social = "Nome alterado depois da preparação"
    nota.tomador.save()
    nota.refresh_from_db()
    assert nota.tomador_snapshot["razao_social"] == nome
    assert nota.servico_snapshot["valor_servicos"] == "1232.25"
    assert nota.perfil_snapshot["aliquota_iss"] == "5"
    assert nota.contrato_id is None
    salvar(nota)
    assert nota.history.count() == 2
    assert nota.tomador_snapshot["razao_social"] == nota.tomador.razao_social
    assert nota.history.last().tomador_snapshot["razao_social"] == nome


def test_retencoes_federais_e_iss(nota):
    nota.valor_servicos = Decimal("1000")
    nota.perfil.iss_retido = True
    for tributo, taxa in [("ir", "1.50"), ("inss", "11"), ("pis", "0.65"), ("cofins", "3"), ("csll", "1")]:
        setattr(nota.perfil, f"reter_{tributo}", True)
        setattr(nota.perfil, f"aliquota_{tributo}", Decimal(taxa))
    calcular(nota, nota.perfil)
    assert nota.valor_iss_retido == Decimal("50")
    assert nota.valor_pis == Decimal("6.50")
    assert nota.valor_liquido == Decimal("778.50")


def test_descontos_e_deducoes(nota):
    nota.valor_servicos = Decimal("1000")
    nota.valor_deducoes = Decimal("100")
    nota.desconto_incondicionado = Decimal("50")
    nota.desconto_condicionado = Decimal("30")
    calcular(nota, nota.perfil)
    assert nota.base_calculo == Decimal("850")
    assert nota.valor_iss == Decimal("42.50")
    assert nota.valor_liquido == Decimal("920")


def test_simples_exige_aliquota_e_mei_zero(nota):
    nota.empresa.optante_simples = True
    with pytest.raises(ValidationError, match="Simples"):
        calcular(nota, nota.perfil)
    nota.aliquota_iss = Decimal("2.50")
    calcular(nota, nota.perfil)
    assert nota.valor_iss == Decimal("30.81")
    nota.empresa.regime_tributario = nota.empresa.Regime.MEI
    calcular(nota, nota.perfil)
    assert nota.valor_iss == 0


@pytest.mark.parametrize("campo,valor", [("valor_servicos", -1), ("valor_servicos", 1.1),
    ("valor_servicos", Decimal("NaN")), ("valor_servicos", Decimal("Infinity")),
    ("valor_servicos", "inválido"), ("valor_deducoes", Decimal("1500")),
    ("outras_retencoes", Decimal("2000"))])
def test_rejeita_valores_invalidos(nota, campo, valor):
    setattr(nota, campo, valor)
    with pytest.raises(ValidationError):
        calcular(nota, nota.perfil)


def test_aliquotas_invalidas(nota):
    nota.perfil.aliquota_iss = Decimal("101")
    with pytest.raises(ValidationError):
        calcular(nota, nota.perfil)
    nota.perfil.aliquota_iss = Decimal("5")
    nota.perfil.aliquota_ir = Decimal("101")
    with pytest.raises(ValidationError):
        calcular(nota, nota.perfil)


def test_produto_bloqueado(nota):
    nota.item_catalogo.natureza = "PRODUTO"
    with pytest.raises(ValidationError, match="NF-e"):
        salvar(nota)
    assert not NotaFiscal.objects.exists()


def test_vinculo_outra_empresa_bloqueado(nota):
    from apps.core.models import Empresa

    outra = Empresa.objects.create(razao_social="Outra", cnpj="00000000000000")
    nota.perfil.empresa = outra
    with pytest.raises(ValidationError, match="mesma empresa"):
        salvar(nota)


def test_tomador_diferente_contrato(nota, contrato):
    contrato.cliente_id = None
    nota.contrato = contrato
    with pytest.raises(ValidationError, match="cliente do contrato"):
        salvar(nota)


def test_item_inativo(nota):
    nota.item_catalogo.ativo = False
    with pytest.raises(ValidationError, match="ativos"):
        salvar(nota)


def test_fluxo_local_criacao_edicao_e_leitura(cli, nota, client, leitor):
    dados = {"tomador": nota.tomador_id, "item_catalogo": nota.item_catalogo_id,
             "perfil": nota.perfil_id, "competencia": "2026-10-01", "discriminacao": "Suporte",
             "valor_servicos": "1.000,00", "valor_deducoes": "0", "desconto_incondicionado": "0",
             "desconto_condicionado": "0", "outras_retencoes": "0", "aliquota_iss": "5"}
    for rota in ("nota_lista", "nota_nova", "perfil_lista", "perfil_novo"):
        assert cli.get(reverse(f"fiscal:{rota}")).status_code == 200
    assert cli.post(reverse("fiscal:nota_nova"), dados).status_code == 302
    criada = NotaFiscal.objects.get()
    assert criada.valor_iss == Decimal("50")
    assert cli.get(reverse("fiscal:nota_detalhe", args=[criada.pk])).status_code == 200
    dados["valor_servicos"] = "2.000,00"
    assert cli.post(reverse("fiscal:nota_editar", args=[criada.pk]), dados).status_code == 302
    criada.refresh_from_db()
    assert criada.valor_iss == Decimal("100")
    assert criada.history.count() == 2
    client.force_login(leitor)
    assert client.post(reverse("fiscal:nota_nova"), dados).status_code == 403


def test_formulario_erro_sem_persistir(cli, nota):
    nota.item_catalogo.natureza = "PRODUTO"
    nota.item_catalogo.save()
    dados = {"tomador": nota.tomador_id, "item_catalogo": nota.item_catalogo_id,
             "perfil": nota.perfil_id, "competencia": "2026-10-01", "discriminacao": "Mercadoria",
             "valor_servicos": "100", "valor_deducoes": "0", "desconto_incondicionado": "0",
             "desconto_condicionado": "0", "outras_retencoes": "0", "aliquota_iss": "5"}
    r = cli.post(reverse("fiscal:nota_nova"), dados)
    assert r.status_code == 200 and "NF-e" in r.content.decode()
    assert not NotaFiscal.objects.exists()


def test_operacao_sem_acesso_fiscal(client, empresa, django_user_model):
    from django.contrib.auth.models import Group

    tecnico = django_user_model.objects.create_user(email="tecnico@teste.local", empresa=empresa)
    tecnico.groups.add(Group.objects.get(name="Operação"))
    client.force_login(tecnico)
    assert client.get(reverse("fiscal:nota_lista")).status_code == 403
    assert client.get(reverse("fiscal:perfil_lista")).status_code == 403
