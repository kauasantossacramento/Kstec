"""WhatsApp do administrador: alteração de valor a partir de uma competência, recebidos, baixa com data e documentos."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.contratos.models import somar_meses
from apps.faturamento.models import CicloFaturamento
from apps.faturamento.services import ciclos, valores
from apps.mensageria.models import Confirmacao
from apps.mensageria.services import assistente, comandos, confirmacoes
from tests.test_a_receber import cenario as fixture_cenario
from tests.test_whatsapp_receber_proximas import agenda as fixture_agenda

cenario = fixture_cenario
agenda = fixture_agenda


def responder(empresa, texto):
    return comandos.responder_admin(empresa, comandos.normalizar(texto), "5575999990000")


def ferramenta(empresa, nome, anexos=None):
    return next(f for f in assistente.ferramentas(empresa, anexos if anexos is not None else []) if f.__name__ == nome)


def test_alterar_valor_vale_a_partir_da_competencia(empresa, agenda):
    alvo = somar_meses(timezone.localdate().replace(day=1), 1)
    em_preparo = CicloFaturamento.objects.get(agenda=agenda, competencia=somar_meses(alvo, 1))
    CicloFaturamento.objects.filter(pk=em_preparo.pk).update(status="AGUARDANDO")
    texto = ferramenta(empresa, "alterar_valor_contrato")("012/2026", 2300, f"{alvo:%m/%Y}", "reajuste IPCA")
    c = Confirmacao.objects.get(acao="faturamento.alterar_valor")
    assert f"SIM {c.codigo}" in texto and "R$ 2.150,00" in texto and "R$ 2.300,00" in texto
    assert f"{alvo:%m/%Y}" in texto and "Não serão alterados" in texto and "aguardando confirmação" in texto
    agenda.refresh_from_db()
    assert agenda.valor == Decimal("2150")  # nada muda antes do SIM

    _, resultado = confirmacoes.responder(empresa, c.codigo, True)
    agenda.refresh_from_db()
    agenda.contrato.refresh_from_db()
    assert agenda.valor == Decimal("2300") and agenda.contrato.valor_mensal == Decimal("2300")
    assert "reajuste IPCA" in agenda.observacoes and "Revise na tela" in resultado
    ciclos.planejar(agenda, horizonte_dias=150)  # o planejamento não reverte o antes nem o depois
    for ciclo in CicloFaturamento.objects.filter(agenda=agenda):
        if ciclo.pk == em_preparo.pk:
            assert ciclo.valor == Decimal("2150")
        elif ciclo.competencia < alvo:
            assert ciclo.valor == Decimal("2150") and ciclo.personalizado
        else:
            assert ciclo.valor == Decimal("2300"), ciclo
    assert CicloFaturamento.objects.filter(agenda=agenda, competencia__gt=somar_meses(alvo, 1)).exists()


def test_alterar_valor_recusa_se_mudou_e_nao_cancela(empresa, agenda):
    alvo = somar_meses(timezone.localdate().replace(day=1), 1)
    ferramenta(empresa, "alterar_valor_contrato")("012", 2400, f"{alvo:%m/%Y}")
    c = Confirmacao.objects.get(acao="faturamento.alterar_valor")
    _, resultado = confirmacoes.responder(empresa, c.codigo, False)
    agenda.refresh_from_db()
    assert agenda.valor == Decimal("2150") and "não foi alterado" in resultado

    ferramenta(empresa, "alterar_valor_contrato")("012", 2400, f"{alvo:%m/%Y}")
    c = Confirmacao.objects.filter(acao="faturamento.alterar_valor", status="PENDENTE").get()
    type(agenda).objects.filter(pk=agenda.pk).update(valor=Decimal("2200"))
    _, resultado = confirmacoes.responder(empresa, c.codigo, True)
    assert "Não alterado" in resultado and "R$ 2.200,00" in resultado
    with pytest.raises(Exception, match="já está"):
        valores.previa(type(agenda).objects.get(pk=agenda.pk), Decimal("2200"), alvo)


def test_entradas_resume_o_que_foi_recebido(empresa, cenario):
    from apps.financeiro.models import Lancamento
    from apps.financeiro.services.lancamentos import baixar

    assert "Nenhum recebimento" in responder(empresa, "entradas")[0][0]
    baixar(Lancamento.objects.get(descricao="NFS-e 2"), data_pagamento=cenario["hoje"], forma_pagamento="PIX")
    texto = responder(empresa, "entradas")[0][0]
    assert "Recebido de" in texto and "012/2026" in texto and "NFS-e 2" in texto and "R$ 1.000,00" in texto
    assert "PIX" in texto and "NFS-e 1" not in texto
    resumo = ferramenta(empresa, "recebimentos_realizados")(contrato="012")
    assert "NFS-e 2" in resumo
    assert "Nenhum recebimento" in ferramenta(empresa, "recebimentos_realizados")(contrato="inexistente")


def test_registrar_recebimento_com_data_informada(empresa, cenario):
    from apps.financeiro.models import Lancamento

    ontem = cenario["hoje"] - timedelta(days=1)
    registrar = ferramenta(empresa, "registrar_recebimento")
    assert "não pode ser futura" in registrar(f"{cenario['anterior']:%m/%Y}",
                                              data_pagamento=f"{cenario['hoje'] + timedelta(days=2):%d/%m/%Y}")
    texto = registrar(f"{cenario['anterior']:%m/%Y}", forma="PIX", data_pagamento=f"{ontem:%d/%m/%Y}")
    c = Confirmacao.objects.get(acao="financeiro.receber")
    assert f"recebido em {ontem:%d/%m/%Y}" in texto and f"SIM {c.codigo}" in texto
    _, resultado = confirmacoes.responder(empresa, c.codigo, True)
    lanc = Lancamento.objects.get(descricao="NFS-e 2")
    assert lanc.status == "PAGO" and lanc.data_pagamento == ontem and lanc.forma_pagamento == "PIX"
    assert f"{ontem:%d/%m/%Y}" in resultado


def test_documentos_da_competencia(empresa, cenario, monkeypatch):
    from apps.core.models import Anexo
    from apps.fiscal.services import pdf_nfse, recibo

    monkeypatch.setattr(pdf_nfse, "garantir_pdf", lambda nota: Anexo.criar(nota, "danfse.pdf", b"%PDF-1.4 nota"))
    monkeypatch.setattr(recibo, "gerar", lambda nota: Anexo.criar(nota, f"recibo_nfse_{nota.numero_nfse}.pdf", b"%PDF r"))
    textos, anexos = responder(empresa, f"documentos 012 {cenario['mes']:%m/%Y}")
    assert [a.nome for a in anexos] == ["danfse.pdf", "recibo_nfse_1.pdf"]
    assert "NFS-e 1" in textos[0] and "relatório de atividades: não há" in textos[0]
    assert "SLA" not in textos[0]  # contrato não exige SLA e não foi pedido

    _, anexos = responder(empresa, f"docs 012 {cenario['mes']:%m/%Y} recibo")
    assert [a.nome for a in anexos] == ["recibo_nfse_1.pdf"]
    assert Anexo.objects.filter(nome="recibo_nfse_1.pdf").count() == 1  # reaproveita o recibo já gerado

    textos, anexos = responder(empresa, "documentos 012 01/2020 nota contrato")
    assert anexos == [] and "sem nota autorizada" in textos[0] and "nenhum arquivo em Contrato" in textos[0]
    assert "não encontrado" in responder(empresa, "documentos zzz 10/2026")[0][0]

    anexos_ia = []
    texto = ferramenta(empresa, "enviar_documentos", anexos_ia)("012", f"{cenario['mes']:%m/%Y}", "nota, recibo")
    assert "Documentos" in texto and len(anexos_ia) == 2


def test_ajuda_lista_entradas_e_documentos(empresa):
    texto = responder(empresa, "ajuda")[0][0]
    assert "*entradas*" in texto and "*documentos 136 10/2026*" in texto
