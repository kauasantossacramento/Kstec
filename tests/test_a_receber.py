"""Indicadores de valores: a receber (só notas autorizadas), faturado por competência × emitido, filtro por mês e baixa em lote."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.financeiro.services import indicadores


@pytest.fixture
def cenario(empresa, contrato):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed
    from apps.financeiro.models import CategoriaFinanceira, ContaBancaria, Lancamento
    from apps.financeiro.services.lancamentos import centro_contrato
    from apps.fiscal.models import NotaFiscal, PerfilFiscal

    seed(empresa)
    item = ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP")
    perfil = PerfilFiscal.objects.create(empresa=empresa, nome="P", aliquota_iss=Decimal("2"))
    conta = ContaBancaria.objects.create(empresa=empresa, nome="BB")
    cat = CategoriaFinanceira.objects.create(empresa=empresa, nome="Rec", tipo="RECEITA", grupo_dre="RECEITA_BRUTA")
    hoje = timezone.localdate()
    agora = timezone.now()

    def nota(num, comp, status="AUTORIZADA", venc=None, valor="1000"):
        n = NotaFiscal.objects.create(empresa=empresa, tomador=contrato.cliente, contrato=contrato, competencia=comp,
                                      item_catalogo=item, perfil=perfil, valor_servicos=Decimal(valor), valor_liquido=Decimal(valor),
                                      discriminacao="x", status=status, numero_nfse=num, ambiente=1)
        NotaFiscal.objects.filter(pk=n.pk).update(autorizada_em=agora)
        Lancamento.objects.create(empresa=empresa, tipo="RECEITA", descricao=f"NFS-e {num}", nota_fiscal=n, categoria=cat,
                                  centro_custo=centro_contrato(contrato), valor=Decimal(valor), conta_bancaria=conta,
                                  data_competencia=comp, data_vencimento=venc or hoje + timedelta(days=20))
        return n
    mes = hoje.replace(day=1)
    anterior = (mes - timedelta(days=1)).replace(day=1)
    nota("1", mes)                                              # competência do mês, a vencer
    nota("2", anterior, venc=hoje - timedelta(days=40))         # competência anterior emitida agora, vencida
    nota("3", anterior, status="CANCELADA")                     # cancelada: não é a receber
    return {"hoje": hoje, "mes": mes, "anterior": anterior, "conta": conta}


def test_somas_compativeis_com_o_real(empresa, cenario):
    r = indicadores.resumo(empresa, cenario["hoje"])
    assert r["total"] == Decimal("2000") and r["vencido"] == Decimal("1000") and len(r["linhas"]) == 2
    f = indicadores.faturamento(empresa, cenario["mes"])
    assert f["total_competencia"] == Decimal("1000")             # só a competência do mês
    assert f["total_emitidas"] == Decimal("2000") and f["total_atrasadas"] == Decimal("1000")
    por_comp = indicadores.resumo(empresa, cenario["hoje"], mes=cenario["anterior"], base="competencia")
    assert por_comp["total"] == Decimal("1000")


def test_painel_e_tela_a_receber_com_filtro_por_mes(cli, empresa, cenario):
    painel = cli.get(reverse("painel:home")).content.decode()
    assert reverse("financeiro:a_receber") in painel and reverse("financeiro:faturamento_mes") in painel
    pagina = cli.get(reverse("financeiro:a_receber")).content.decode()
    assert "NFS-e 1" in pagina and "NFS-e 2" in pagina and "NFS-e 3" not in pagina
    mes = cli.get(reverse("financeiro:a_receber") + f"?mes={cenario['anterior']:%Y-%m}&base=competencia").content.decode()
    assert "NFS-e 2" in mes and "NFS-e 1" not in mes
    assert cli.get(reverse("financeiro:faturamento_mes")).status_code == 200


def test_baixa_em_lote(cli, empresa, cenario):
    from apps.financeiro.models import Lancamento

    ids = [str(x) for x in Lancamento.objects.filter(nota_fiscal__status="AUTORIZADA").values_list("pk", flat=True)]
    dados = {"selecionados": ids, "data_pagamento": cenario["hoje"].isoformat(), "conta_bancaria": cenario["conta"].pk,
             "forma_pagamento": "OB", **{f"ob_{i}": f"2026OB{n}" for n, i in enumerate(ids)}}
    assert cli.post(reverse("financeiro:a_receber") + "?mes=todos", dados).status_code == 302
    assert Lancamento.objects.filter(pk__in=ids, status="PAGO").count() == 2
    assert indicadores.resumo(empresa, cenario["hoje"])["total"] == 0
    assert indicadores.recebido(empresa, cenario["hoje"].replace(day=1))["total"] == Decimal("2000")
