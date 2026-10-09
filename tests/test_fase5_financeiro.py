from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.core.agenda import eventos
from apps.financeiro.models import CategoriaFinanceira, CentroCusto, ContaBancaria, Lancamento, Recorrencia
from apps.financeiro.seeds import seed
from apps.financeiro.services import lancamentos, recorrencias, relatorios


@pytest.fixture
def lancamento(empresa, contrato):
    seed(empresa)
    hoje = timezone.localdate()
    conta = ContaBancaria.objects.create(nome="Conta de testes", saldo_inicial=Decimal("100"), data_saldo_inicial=hoje - timedelta(days=365))
    return Lancamento(empresa=empresa, tipo="RECEITA", descricao="Mensalidade sintética",
        categoria=CategoriaFinanceira.objects.get(nome="Contratos públicos"), centro_custo=contrato.centro_custo,
        conta_bancaria=conta, valor=Decimal("1000"), data_competencia=hoje, data_vencimento=hoje)


def test_centro_automatico_e_seed_idempotente(empresa, contrato):
    assert contrato.centro_custo.empresa == empresa
    seed(empresa)
    seed(empresa)
    assert CategoriaFinanceira.objects.filter(empresa=empresa).count() == 14
    assert CentroCusto.objects.filter(contrato=contrato).count() == 1


def test_baixa_decimal_ob_auditoria_e_saldo(lancamento):
    lancamentos.salvar(lancamento)
    obj = lancamentos.baixar(lancamento, timezone.localdate(), "OB", juros=Decimal("10"), multa=Decimal("5"), desconto=Decimal("20"), ordem_bancaria="OB-TESTE")
    assert obj.valor_pago == Decimal("995")
    assert obj.history.count() == 2
    assert relatorios.saldos_contas(obj.empresa, timezone.localdate())[0]["saldo"] == Decimal("1095")
    with pytest.raises(ValidationError, match="pago"):
        lancamentos.baixar(obj, timezone.localdate(), "PIX")
    with pytest.raises(ValidationError):
        lancamentos.salvar(obj)


@pytest.mark.parametrize("kwargs", [{"forma_pagamento": "INVALIDA"}, {"forma_pagamento": "OB"},
    {"data_pagamento": timezone.localdate() + timedelta(days=1)}, {"desconto": Decimal("1000")},
    {"juros": -1}, {"juros": 1.1}])
def test_baixa_invalida_preserva_pendente(lancamento, kwargs):
    lancamentos.salvar(lancamento)
    dados = {"data_pagamento": timezone.localdate(), "forma_pagamento": "PIX", **kwargs}
    with pytest.raises(ValidationError):
        lancamentos.baixar(lancamento, **dados)
    lancamento.refresh_from_db()
    assert lancamento.status == "PENDENTE"
    assert lancamento.history.count() == 1


def test_atraso_cancelamento_e_exclusao_dos_totais(lancamento):
    lancamento.data_vencimento -= timedelta(days=5)
    lancamentos.salvar(lancamento)
    assert lancamentos.marcar_atrasados(lancamento.empresa) == 1
    assert lancamentos.marcar_atrasados(lancamento.empresa) == 0
    with pytest.raises(ValidationError):
        lancamentos.cancelar(lancamento, " ")
    obj = lancamentos.cancelar(lancamento, "Cancelamento de teste")
    assert obj.history.count() == 3
    assert relatorios.dre(obj.empresa, obj.data_competencia, obj.data_competencia)["receita_bruta"] == 0


def test_dre_competencia_caixa_pagamento_e_contrato(lancamento):
    lancamentos.salvar(lancamento)
    hoje = timezone.localdate()
    contrato = lancamento.centro_custo.contrato
    assert relatorios.dre(lancamento.empresa, hoje, hoje, contrato)["resultado"] == Decimal("1000")
    assert relatorios.fluxo_caixa(lancamento.empresa, hoje, hoje)["entradas"] == 0
    assert relatorios.fluxo_caixa(lancamento.empresa, hoje, hoje)["entradas_previstas"] == Decimal("1000")
    lancamentos.baixar(lancamento, hoje, "PIX")
    assert relatorios.fluxo_caixa(lancamento.empresa, hoje, hoje)["entradas"] == Decimal("1000")
    assert relatorios.fluxo_caixa(lancamento.empresa, hoje, hoje)["entradas_previstas"] == 0


def test_resultado_nao_operacional_assinado(lancamento):
    for tipo, valor in [("RECEITA", "50"), ("DESPESA", "20")]:
        categoria = CategoriaFinanceira.objects.create(nome=f"Não operacional {tipo}", tipo=tipo, grupo_dre="NAO_OPERACIONAL")
        novo = Lancamento(empresa=lancamento.empresa, tipo=tipo, descricao=tipo, categoria=categoria,
            centro_custo=lancamento.centro_custo, conta_bancaria=lancamento.conta_bancaria, valor=Decimal(valor),
            data_competencia=lancamento.data_competencia, data_vencimento=lancamento.data_vencimento)
        lancamentos.salvar(novo)
    dados = relatorios.dre(lancamento.empresa, lancamento.data_competencia, lancamento.data_competencia)
    assert dados["nao_operacional"] == Decimal("30")
    assert dados["resultado"] == Decimal("30")


def test_categoria_incompativel_e_vinculo_outra_empresa(lancamento):
    lancamento.tipo = "DESPESA"
    with pytest.raises(ValidationError):
        lancamentos.salvar(lancamento)
    lancamento.tipo = "RECEITA"
    from apps.core.models import Empresa
    outra = Empresa.objects.create(cnpj="11222333000181", razao_social="Outra empresa")
    lancamento.conta_bancaria = ContaBancaria.objects.create(empresa=outra, nome="Conta externa")
    with pytest.raises(ValidationError, match="mesma empresa"):
        lancamentos.salvar(lancamento)


def recorrente(lancamento, **kwargs):
    from datetime import date
    return Recorrencia.objects.create(empresa=lancamento.empresa, dia=31, inicio=date(2026, 1, 1),
        **recorrencias.modelo(lancamento), **kwargs)


def test_recorrencia_idempotente_dia31_e_auditoria(lancamento):
    from datetime import date
    obj = recorrente(lancamento)
    assert recorrencias.gerar(obj, date(2026, 1, 1)) == 12
    assert recorrencias.gerar(obj, date(2026, 1, 1)) == 0
    fevereiro = Lancamento.objects.get(recorrencia=obj, data_competencia=date(2026, 2, 1))
    assert fevereiro.data_vencimento == date(2026, 2, 28)
    assert fevereiro.status == "PREVISTO" and fevereiro.history.count() == 1


def test_recorrencia_anual_fim_e_inativa(lancamento):
    from datetime import date
    anual = recorrente(lancamento, frequencia="ANUAL")
    assert recorrencias.gerar(anual, date(2026, 1, 1)) == 1
    mensal = recorrente(lancamento, fim=date(2026, 2, 28))
    assert recorrencias.gerar(mensal, date(2026, 1, 1)) == 2
    mensal.ativo = False
    mensal.save()
    assert recorrencias.gerar(mensal, date(2027, 1, 1)) == 0


def test_fluxo_http_e_permissoes(cli, leitor, lancamento, django_user_model):
    lancamentos.salvar(lancamento)
    for url in ["financeiro:home", "financeiro:lancamento_lista", "financeiro:demonstrativo", "financeiro:recorrencia_lista"]:
        assert cli.get(reverse(url)).status_code == 200
    assert cli.get(reverse("contratos:contrato_detalhe", args=[lancamento.centro_custo.contrato_id]) + "?aba=financeiro").status_code == 200
    cli.force_login(leitor)
    assert cli.get(reverse("financeiro:home")).status_code == 200
    assert cli.post(reverse("financeiro:baixar", args=[lancamento.pk]), {}).status_code == 403
    tecnico = django_user_model.objects.create_user(email="tecnico-fin@test.local", password="Senha-test-123", empresa=lancamento.empresa)
    tecnico.groups.add(Group.objects.get(name="Operação"))
    cli.force_login(tecnico)
    assert cli.get(reverse("financeiro:home")).status_code == 403
    assert cli.get(reverse("financeiro:lancamento_detalhe", args=[lancamento.pk])).status_code == 403
    assert all(e.tipo != "FINANCEIRO" for e in eventos(lancamento.empresa, lancamento.data_vencimento, lancamento.data_vencimento, tecnico))
    assert cli.get(reverse("financeiro:demonstrativo") + "?inicio=invalida").status_code == 403


def test_formulario_baixa_http_com_auditoria(cli, lancamento):
    lancamentos.salvar(lancamento)
    url = reverse("financeiro:baixar", args=[lancamento.pk])
    assert cli.get(url).status_code == 200
    response = cli.post(url, {"data_pagamento": timezone.localdate().isoformat(), "forma_pagamento": "PIX",
                             "juros": "0,00", "multa": "0,00", "desconto": "0,00"})
    assert response.status_code == 302
    lancamento.refresh_from_db()
    assert lancamento.status == "PAGO"
    assert str(lancamento.history.latest().history_user_id) == cli.session["_auth_user_id"]


def test_aging_limites_e_cancelados(lancamento):
    hoje = timezone.localdate()
    for dias in [-1, 0, 1, 30, 31, 60, 61, 90, 91]:
        novo = Lancamento(empresa=lancamento.empresa, **recorrencias.modelo(lancamento),
                           data_competencia=hoje, data_vencimento=hoje - timedelta(days=dias))
        lancamentos.salvar(novo)
    faixas = relatorios.aging(lancamento.empresa, hoje)
    assert [f["quantidade"] for f in faixas] == [2, 2, 2, 2, 1]
    assert [f["total"] for f in faixas] == [Decimal("2000")] * 4 + [Decimal("1000")]


def test_edicao_categoria_usada_bloqueada(cli, lancamento):
    lancamentos.salvar(lancamento)
    categoria = lancamento.categoria
    response = cli.post(reverse("financeiro:categoria_editar", args=[categoria.pk]), {
        "nome": categoria.nome, "tipo": "DESPESA", "grupo_dre": "CUSTO_SERVICO", "ativo": "on"})
    assert response.status_code == 200
    assert "Categorias utilizadas" in response.content.decode()
    categoria.refresh_from_db()
    assert categoria.tipo == "RECEITA"


def test_formulario_recorrencia_geracao_http(cli, lancamento):
    hoje = timezone.localdate()
    response = cli.post(reverse("financeiro:recorrencia_nova"), {
        "descricao": "Recorrência HTTP de teste", "tipo": "RECEITA", "categoria": lancamento.categoria_id,
        "centro_custo": lancamento.centro_custo_id, "conta_bancaria": lancamento.conta_bancaria_id,
        "valor": "1.000,00", "frequencia": "MENSAL", "dia": "31", "inicio": hoje.replace(day=1).isoformat(), "ativo": "on"})
    assert response.status_code == 302
    obj = Recorrencia.objects.get(descricao="Recorrência HTTP de teste")
    url = reverse("financeiro:gerar_recorrencia", args=[obj.pk])
    assert cli.get(url).status_code == 405
    assert cli.post(url).status_code == 302
    assert Lancamento.objects.filter(recorrencia=obj).count() == 12
    assert cli.post(url).status_code == 302
    assert Lancamento.objects.filter(recorrencia=obj).count() == 12
