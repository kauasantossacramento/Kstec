"""WhatsApp do administrador: próximas emissões, contratos e baixa de recebimentos por competência (com confirmação)."""

from datetime import date, time
from decimal import Decimal

import pytest

from apps.mensageria.models import Confirmacao
from apps.mensageria.services import comandos, confirmacoes
from tests.test_a_receber import cenario as fixture_cenario

cenario = fixture_cenario


def responder(empresa, texto):
    return comandos.responder_admin(empresa, comandos.normalizar(texto), "5575999990000")[0][0]


def test_receber_lista_por_competencia(empresa, cenario):
    texto = responder(empresa, "receber")
    assert "A receber" in texto and f"*{cenario['mes']:%m/%Y}*" in texto and f"*{cenario['anterior']:%m/%Y}*" in texto
    assert "NFS-e 1" in texto and "NFS-e 2" in texto and "NFS-e 3" not in texto and "⚠️" in texto


def test_recebido_pede_confirmacao_e_sim_da_baixa(empresa, cenario):
    from apps.financeiro.models import Lancamento

    comp = cenario["anterior"]
    texto = responder(empresa, f"Recebido 012/2026 {comp:%m/%Y} pix")
    assert "Confirmar recebimento" in texto and "NFS-e 2" in texto and "NFS-e 1" not in texto and "PIX" in texto
    c = Confirmacao.objects.get(acao="financeiro.receber")
    assert Lancamento.objects.get(descricao="NFS-e 2").status != "PAGO"  # nada muda antes do SIM
    _, resultado = confirmacoes.responder(empresa, c.codigo, True)
    lanc = Lancamento.objects.get(descricao="NFS-e 2")
    assert lanc.status == "PAGO" and lanc.forma_pagamento == "PIX" and "1 recebimento(s) baixado(s)" in resultado
    assert Lancamento.objects.get(descricao="NFS-e 1").status != "PAGO"
    assert "Nenhuma nota em aberto" in responder(empresa, f"recebido {comp:%m/%Y}")


def test_recebido_nao_cancela_e_contrato_inexistente(empresa, cenario):
    from apps.financeiro.models import Lancamento

    texto = responder(empresa, f"recebido {cenario['mes']:%m/%Y}")
    c = Confirmacao.objects.get(acao="financeiro.receber")
    assert f"SIM {c.codigo}" in texto
    confirmacoes.responder(empresa, c.codigo, False)
    assert not Lancamento.objects.filter(status="PAGO").exists()
    assert "Nenhuma nota em aberto do contrato invicta" in responder(empresa, f"recebido invicta {cenario['mes']:%m/%Y}")
    assert "Competência inválida" in responder(empresa, "recebido 13/2026")


@pytest.fixture
def agenda(empresa, contrato):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed
    from apps.faturamento.models import AgendaFaturamento
    from apps.faturamento.services import ciclos

    seed(empresa)
    contrato.vigencia_fim = date(2027, 6, 30)
    contrato.save()
    a = AgendaFaturamento.objects.create(
        empresa=empresa, contrato=contrato, item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
        valor=Decimal("2150"), dia_emissao=27, hora_emissao=time(8), inicio=date(2026, 1, 1), ativa_desde=date(2026, 1, 1),
        referencia="MES_CORRENTE", tipo_vencimento="PRAZO", prazo_dias=30)
    ciclos.planejar(a, horizonte_dias=90)
    return a


def test_proximas_e_contratos_trazem_objeto_resumido(empresa, agenda):
    texto = responder(empresa, "próximas")
    assert "Próximas emissões" in texto and "012/2026 — Manutenção e suporte do sistema de protocolo" in texto
    assert "R$ 2.150,00" in texto
    texto = responder(empresa, "contratos")
    assert "Contratos vigentes" in texto and "MUNICIPIO DE VALENCA" in texto and "próxima emissão" in texto


def test_ajuda_lista_os_novos_comandos(empresa):
    texto = responder(empresa, "ajuda")
    assert "*proximas*" in texto and "*receber*" in texto and "*recebido 10/2026*" in texto
