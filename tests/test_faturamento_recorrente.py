"""Faturamento recorrente: calendário, planejamento idempotente, execução segura e previsão de recebimentos."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from freezegun import freeze_time

from apps.catalogo.models import ItemCatalogo
from apps.catalogo.seeds import seed as seed_catalogo
from apps.core.travas import trava
from apps.faturamento.models import AgendaFaturamento, AjustePrevisao, CicloFaturamento
from apps.faturamento.services import calendario, ciclos, previsao
from apps.financeiro.models import CategoriaFinanceira, Lancamento
from apps.financeiro.services.lancamentos import centro_contrato
from apps.fiscal.models import ConfiguracaoFiscal, NotaFiscal, PerfilFiscal

S = CicloFaturamento.Status


@pytest.fixture
def fiscal(empresa):
    seed_catalogo(empresa)
    perfil = PerfilFiscal.objects.create(empresa=empresa, nome="Simples sem retenção", aliquota_iss=Decimal("2"))
    config = ConfiguracaoFiscal.objects.create(empresa=empresa, perfil_padrao=perfil, aliquota_iss=Decimal("2"),
                                               total_tributos_simples=Decimal("6"))
    return ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"), perfil, config


@pytest.fixture
def agenda(contrato, fiscal):
    item, _, _ = fiscal
    return AgendaFaturamento.objects.create(
        empresa=contrato.empresa, contrato=contrato, item_catalogo=item, valor=Decimal("5000.00"),
        referencia="MES_ANTERIOR", dia_emissao=5, hora_emissao=time(8), tipo_vencimento="PRAZO", prazo_dias=30,
        modo="RASCUNHO", inicio=date(2026, 9, 1), ativa_desde=date(2026, 10, 1))


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------

def test_calendario_mes_anterior_dia_util_e_vencimentos(agenda):
    assert calendario.data_emissao(agenda, date(2026, 9, 1)) == date(2026, 10, 5)
    # 05/12/2026 é sábado → segunda 07/12
    assert calendario.data_emissao(agenda, date(2026, 11, 1)) == date(2026, 12, 7)
    agenda.dia_util = False
    assert calendario.data_emissao(agenda, date(2026, 11, 1)) == date(2026, 12, 5)
    agenda.dia_emissao = 31
    assert calendario.data_emissao(agenda, date(2027, 1, 1)) == date(2027, 2, 28)
    assert calendario.data_vencimento(agenda, date(2026, 10, 5)) == date(2026, 11, 4)
    agenda.tipo_vencimento, agenda.dia_vencimento = "DIA_FIXO", 10
    assert calendario.data_vencimento(agenda, date(2026, 10, 5)) == date(2026, 10, 10)
    assert calendario.data_vencimento(agenda, date(2026, 10, 15)) == date(2026, 11, 10)


def test_competencias_respeitam_vigencia_e_mes_corrente(agenda):
    todas = list(calendario.competencias(agenda))
    assert [p.competencia.month for p in todas] == [9, 10, 11, 12]
    agenda.referencia = "MES_CORRENTE"
    assert calendario.data_emissao(agenda, date(2026, 10, 1)) == date(2026, 10, 5)


# ---------------------------------------------------------------------------
# Planejamento
# ---------------------------------------------------------------------------

def test_planejar_idempotente_e_respeita_ativacao(agenda):
    assert ciclos.planejar(agenda, hoje=date(2026, 10, 1)) == 2
    assert ciclos.planejar(agenda, hoje=date(2026, 10, 1)) == 0
    assert list(agenda.ciclos.values_list("competencia", flat=True)) == [date(2026, 9, 1), date(2026, 10, 1)]
    agenda.ativa_desde = date(2026, 10, 6)
    agenda.save()
    agenda.ciclos.all().delete()
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    assert agenda.ciclos.count() == 1  # emissão de 05/10 é anterior à ativação


def test_planejar_sincroniza_programados_mas_preserva_personalizados(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    setembro, outubro = agenda.ciclos.order_by("competencia")
    ciclos.ajustar(outubro, valor=Decimal("4200"), data_emissao=date(2026, 11, 3), data_vencimento=date(2026, 11, 20),
                   discriminacao_texto="Mês com desconto acordado")
    agenda.valor = Decimal("5500")
    agenda.save()
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    setembro.refresh_from_db()
    outubro.refresh_from_db()
    assert setembro.valor == Decimal("5500")
    assert outubro.valor == Decimal("4200") and outubro.personalizado


def test_agenda_pausada_nao_planeja_nem_processa(agenda):
    agenda.ativo = False
    agenda.save()
    assert ciclos.planejar(agenda, hoje=date(2026, 10, 1)) == 0


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

@freeze_time("2026-10-05 09:00:00-03:00")
def test_modo_rascunho_gera_uma_unica_nota(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.get(competencia=date(2026, 9, 1))
    ciclo = ciclos.executar(ciclo)
    assert ciclo.status == S.RASCUNHO and ciclo.nota.status == NotaFiscal.Status.RASCUNHO
    assert ciclo.nota.contrato == agenda.contrato and ciclo.nota.valor_servicos == Decimal("5000.00")
    assert "09/2026" in ciclo.nota.discriminacao
    assert ciclo.nota.vencimento_recebivel == date(2026, 11, 4)
    ciclos.executar(ciclo)
    assert NotaFiscal.objects.filter(contrato=agenda.contrato).count() == 1


@freeze_time("2026-10-05 09:00:00-03:00")
def test_processar_respeita_horario_e_data(agenda):
    agenda.hora_emissao = time(10)
    agenda.save()
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    assert ciclos.processar() == 0  # 09h < 10h
    agenda.hora_emissao = time(8)
    agenda.save()
    assert ciclos.processar() == 1
    assert agenda.ciclos.get(competencia=date(2026, 10, 1)).status == S.PROGRAMADO  # emissão em novembro


@freeze_time("2026-10-05 09:00:00-03:00")
def test_bloqueios_saldo_vigencia_e_configuracao(agenda, fiscal):
    agenda.modo = "CONFIRMAR"
    agenda.save()
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.get(competencia=date(2026, 9, 1))
    ciclo.valor = Decimal("999999")
    ciclo.save()
    assert ciclos.executar(ciclo).status == S.BLOQUEADO
    assert "Saldo contratual" in CicloFaturamento.objects.get(pk=ciclo.pk).mensagem
    ciclo.valor = Decimal("5000")
    ciclo.save()
    ciclo = ciclos.executar(ciclo, manual=True)
    # Configuração sintética sem certificado: validação fiscal bloqueia antes de qualquer envio.
    assert ciclo.status == S.BLOQUEADO and ciclo.nota.status == NotaFiscal.Status.RASCUNHO
    assert not ciclo.nota.tentativas.exists()


@freeze_time("2026-10-30 09:00:00-03:00")
def test_emissao_muito_atrasada_exige_acao_manual(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = ciclos.executar(agenda.ciclos.get(competencia=date(2026, 9, 1)))
    assert ciclo.status == S.BLOQUEADO and ciclo.nota_id is None


def _autorizar(nota):
    NotaFiscal.objects.filter(pk=nota.pk).update(status="AUTORIZADA", numero_nfse="77")


@freeze_time("2026-10-05 09:00:00-03:00")
def test_confirmar_transmite_e_autoriza(agenda, monkeypatch, django_capture_on_commit_callbacks):
    reverse("faturamento:home")  # carrega as URLs antes de substituir garantir_pdf (evita vazar o falso)
    agenda.modo = "CONFIRMAR"
    agenda.save()
    monkeypatch.setattr(ciclos.emissao, "validar_emissao", lambda nota, config: None)
    monkeypatch.setattr(ciclos.emissao, "transmitir", _autorizar)
    monkeypatch.setattr("apps.fiscal.services.pdf_nfse.garantir_pdf", lambda nota: None)
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = ciclos.executar(agenda.ciclos.get(competencia=date(2026, 9, 1)))
    assert ciclo.status == S.AGUARDANDO
    with django_capture_on_commit_callbacks(execute=True):
        ciclo = ciclos.confirmar(ciclo)
    ciclo.refresh_from_db()
    assert ciclo.status == S.AUTORIZADO and ciclo.confirmado_em
    assert any(e["tipo"] == "pos_autorizacao" for e in ciclo.eventos)
    with pytest.raises(ValidationError):
        ciclos.confirmar(ciclo)


@freeze_time("2026-10-05 09:00:00-03:00")
def test_resultado_incerto_vira_transmitido_e_so_consulta(agenda, monkeypatch):
    agenda.modo = "AUTOMATICO"
    agenda.save()
    monkeypatch.setattr(ciclos.emissao, "validar_emissao", lambda nota, config: None)

    def transmitir_incerto(nota):
        from apps.core.models import Anexo
        from apps.fiscal.models import TentativaTransmissao

        TentativaTransmissao.objects.create(empresa=nota.empresa, nota=nota, canal="MUNICIPAL_EL", ambiente=1,
                                            id_dps="X" * 45, hash_requisicao="0" * 64,
                                            dps_assinada=Anexo.criar(nota, "dps.xml", b"<x/>"))
        NotaFiscal.objects.filter(pk=nota.pk).update(status="ERRO_COMUNICACAO")
        raise ValidationError("Resultado inconclusivo. Consulte esta DPS; não repita a emissão.")

    monkeypatch.setattr(ciclos.emissao, "transmitir", transmitir_incerto)
    consultas = []
    monkeypatch.setattr(ciclos.emissao, "consultar", lambda nota: consultas.append(nota.pk) or _autorizar(nota))
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = ciclos.executar(agenda.ciclos.get(competencia=date(2026, 9, 1)))
    assert ciclo.status == S.TRANSMITIDO
    monkeypatch.setattr(ciclos.emissao, "transmitir", lambda nota: pytest.fail("não pode reenviar"))
    ciclos.processar()
    ciclos.acompanhar()
    ciclo.refresh_from_db()
    assert consultas == [ciclo.nota_id] and ciclo.status == S.AUTORIZADO


def test_trava_impede_execucao_concorrente(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.first()
    with trava(f"faturamento:ciclo:{ciclo.pk}"):
        with pytest.raises(ValidationError):
            ciclos.executar(ciclo, manual=True)


def test_pular_retomar_e_ajuste_valida_datas(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.first()
    with pytest.raises(ValidationError):
        ciclos.pular(ciclo, "  ")
    assert ciclos.pular(ciclo, "Serviço suspenso no mês").status == S.PULADO
    assert ciclos.retomar(ciclo).status == S.PROGRAMADO
    with pytest.raises(ValidationError):
        ciclos.ajustar(ciclo, valor=Decimal("1"), data_emissao=date(2026, 10, 10), data_vencimento=date(2026, 10, 1),
                       discriminacao_texto="")


def test_discriminacao_placeholders_e_modelo_invalido(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.first()
    agenda.discriminacao = "Suporte {mes_extenso} · contrato {contrato}"
    assert ciclos.discriminacao(ciclo) == "Suporte setembro/2026 · contrato 012/2026"
    agenda.discriminacao = "Texto com {chave_inexistente}"
    with pytest.raises(ValidationError):
        ciclos.discriminacao(ciclo)


# ---------------------------------------------------------------------------
# Previsão de recebimentos
# ---------------------------------------------------------------------------

def _receita(contrato, valor, vencimento, status="PENDENTE"):
    categoria, _ = CategoriaFinanceira.objects.get_or_create(empresa=contrato.empresa, nome="Contratos públicos",
                                                             defaults={"tipo": "RECEITA", "grupo_dre": "RECEITA_BRUTA"})
    return Lancamento.objects.create(empresa=contrato.empresa, tipo="RECEITA", descricao="Avulsa", pessoa=contrato.cliente,
                                     categoria=categoria, centro_custo=centro_contrato(contrato), valor=Decimal(valor),
                                     data_competencia=vencimento, data_vencimento=vencimento, status=status)


def test_previsao_combina_fontes_sem_duplicar(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    _receita(agenda.contrato, "300.00", date(2026, 11, 10))
    dados = previsao.mes(agenda.empresa, date(2026, 11, 1), hoje=date(2026, 10, 9))
    origens = sorted(i.origem for i in dados["itens"])
    assert origens == ["EM_ABERTO", "PROGRAMADO"]  # ciclo 09/2026 vence 04/11; avulsa 10/11
    assert dados["total"] == Decimal("5300.00")
    dezembro = previsao.mes(agenda.empresa, date(2026, 12, 1), hoje=date(2026, 10, 9))
    assert [i.origem for i in dezembro["itens"]] == ["PROGRAMADO"]  # ciclo 10/2026 vence 05/12
    janeiro = previsao.mes(agenda.empresa, date(2027, 1, 1), hoje=date(2026, 10, 9))
    assert [i.origem for i in janeiro["itens"]] == ["ESTIMADO"]  # competência 11/2026 ainda não planejada


def test_previsao_contrato_sem_agenda_estima_pelo_prazo(contrato):
    contrato.dia_faturamento = 5
    contrato.save()
    dados = previsao.mes(contrato.empresa, date(2026, 11, 1), hoje=date(2026, 10, 9))
    assert [(i.data, i.valor) for i in dados["itens"]] == [(date(2026, 11, 4), Decimal("5000.00"))]


def test_ajuste_mensal_move_altera_e_exclui(agenda):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ajuste = AjustePrevisao.objects.create(empresa=agenda.empresa, contrato=agenda.contrato, mes=date(2026, 11, 1),
                                           data_prevista=date(2026, 11, 20), valor=Decimal("4500"), motivo="Empenho parcial")
    novembro = previsao.mes(agenda.empresa, date(2026, 11, 1), hoje=date(2026, 10, 9))
    item = novembro["itens"][0]
    assert (item.data, item.valor, item.ajuste) == (date(2026, 11, 20), Decimal("4500"), ajuste)
    assert item.original == [(date(2026, 11, 4), Decimal("5000.00"))]
    ajuste.excluir = True
    ajuste.save()
    novembro = previsao.mes(agenda.empresa, date(2026, 11, 1), hoje=date(2026, 10, 9))
    assert novembro["total"] == 0 and novembro["itens"][0].excluido
    ajuste.excluir, ajuste.data_prevista = False, date(2026, 12, 5)
    ajuste.save()
    assert previsao.mes(agenda.empresa, date(2026, 11, 1), hoje=date(2026, 10, 9))["total"] == 0
    assert previsao.mes(agenda.empresa, date(2026, 12, 1), hoje=date(2026, 10, 9))["total"] == Decimal("9500.00")


# ---------------------------------------------------------------------------
# Telas
# ---------------------------------------------------------------------------

def test_telas_e_wizard(cli, agenda, fiscal):
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.first()
    for url in (reverse("faturamento:home"), reverse("faturamento:agenda_nova"), reverse("faturamento:agenda", args=[agenda.pk]),
                reverse("faturamento:agenda_editar", args=[agenda.pk]), reverse("faturamento:ciclo", args=[ciclo.pk]),
                reverse("faturamento:recebimentos") + "?mes=2026-11&dia=2026-11-04",
                reverse("contratos:contrato_detalhe", args=[agenda.contrato_id]) + "?aba=faturamento",
                reverse("faturamento:ajustar_previsao", args=[agenda.contrato_id, "2026-11"])):
        resposta = cli.get(url)
        assert resposta.status_code == 200, url
    simulacao = cli.post(reverse("faturamento:simular"), {
        "agenda_pk": agenda.pk, "item_catalogo": agenda.item_catalogo_id, "valor": "5.000,00", "referencia": "MES_ANTERIOR",
        "dia_emissao": "5", "hora_emissao": "08:00", "tipo_vencimento": "PRAZO", "prazo_dias": "30",
        "inicio": "2026-09-01", "modo": "CONFIRMAR"})
    assert simulacao.status_code == 200 and "Competência" in simulacao.content.decode()


def test_wizard_cria_agenda_e_exige_aceite_automatico(cli, contrato, fiscal):
    item, _, _ = fiscal
    dados = {"contrato": contrato.pk, "item_catalogo": item.pk, "valor": "5.000,00", "discriminacao": "",
             "referencia": "MES_ANTERIOR", "dia_emissao": "5", "hora_emissao": "08:00", "dia_util": "on",
             "tipo_vencimento": "PRAZO", "prazo_dias": "30", "inicio": "2026-09-15", "modo": "AUTOMATICO"}
    resposta = cli.post(reverse("faturamento:agenda_nova"), dados)
    assert resposta.status_code == 200 and not AgendaFaturamento.objects.exists()
    dados["aceite_automatico"] = "on"
    resposta = cli.post(reverse("faturamento:agenda_nova"), dados)
    agenda = AgendaFaturamento.objects.get()
    assert resposta.status_code == 302 and agenda.inicio == date(2026, 9, 1) and agenda.modo == "AUTOMATICO"


def test_ajuste_previsao_pela_tela(cli, agenda):
    url = reverse("faturamento:ajustar_previsao", args=[agenda.contrato_id, "2026-11"])
    assert cli.post(url, {"motivo": "sem alteração"}).status_code == 200  # nada informado
    resposta = cli.post(url, {"data_prevista": "2026-11-25", "motivo": "Pagamento combinado"})
    assert resposta.status_code == 302
    assert AjustePrevisao.objects.get().data_prevista == date(2026, 11, 25)
    cli.post(url, {"remover": "1", "motivo": "x"})
    assert not AjustePrevisao.objects.exists()


def test_leitura_nao_executa(client, leitor, agenda):
    client.force_login(leitor)
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.first()
    assert client.get(reverse("faturamento:home")).status_code == 200
    assert client.post(reverse("faturamento:ciclo_acao", args=[ciclo.pk, "executar"])).status_code == 403


def test_parcela_e_placeholders_de_execucao(agenda):
    contrato = agenda.contrato
    contrato.vigencia_inicio, contrato.vigencia_fim = date(2026, 5, 27), date(2027, 5, 26)
    contrato.save()
    assert calendario.parcela(contrato, date(2026, 6, 1)) == (1, 12)
    assert calendario.parcela(contrato, date(2026, 8, 1)) == (3, 12)
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    ciclo = agenda.ciclos.get(competencia=date(2026, 9, 1))
    agenda.discriminacao = "Competência: {mes_nome} - {parcela2} de {total_parcelas} ({parcela}º mês) · {valor}"
    assert ciclos.discriminacao(ciclo) == "Competência: Setembro - 04 de 12 (4º mês) · R$ 5.000,00"
