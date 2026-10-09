"""WhatsApp: ritmo anti-bloqueio, worker com transporte simulado, comandos, confirmações e envios a clientes."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.cobranca.models import PerfilCobranca
from apps.core.models import Anexo
from apps.core.validadores import formatar_telefone, normalizar_telefone
from apps.financeiro.models import CategoriaFinanceira, Lancamento
from apps.financeiro.services.lancamentos import centro_contrato
from apps.mensageria.models import Confirmacao, ContatoWhatsApp, EstadoSessao, LoteEnvio, MensagemWhatsApp
from apps.mensageria.services import comandos, envios, fila, worker
from apps.mensageria.services.transporte import ErroTransporte, TransporteSimulado

M = MensagemWhatsApp
ADMIN = "5575999990000"


def quando(dia, hora):
    return timezone.make_aware(datetime.combine(dia, time(hora)))


SEGUNDA = date(2026, 10, 5)


@pytest.fixture
def config(empresa):
    c = fila.config_de(empresa)
    c.ativo, c.numeros_admin, c.simular_digitacao = True, ADMIN, False
    c.save()
    fila.estado_de(empresa)
    return c


@pytest.fixture
def contato(pessoa):
    PerfilCobranca.objects.create(empresa=pessoa.empresa, pessoa=pessoa, whatsapp_ativo=True)
    return ContatoWhatsApp.objects.create(empresa=pessoa.empresa, pessoa=pessoa, nome="Maria Gestora",
                                          telefone="(75) 98888-1111", consentimento=True,
                                          origem_consentimento="Cláusula 12 do contrato")


def test_telefones():
    assert normalizar_telefone("(75) 99999-0000") == "5575999990000"
    assert normalizar_telefone("+55 75 3641-0000") == "557536410000"
    assert normalizar_telefone("123") == ""
    assert formatar_telefone("5575999990000") == "(75) 99999-0000"
    assert fila.mesmo_numero("5575999990000", "557599990000")  # JID antigo sem o nono dígito


def test_janela_e_limites_bloqueiam_clientes_mas_nao_admin(empresa, config, contato):
    estado = fila.estado_de(empresa)
    cliente = fila.enfileirar(empresa, contato.telefone, "Olá", contato=contato)
    admin = fila.enfileirar(empresa, ADMIN, "Alerta", para_admin=True)
    sabado = quando(date(2026, 10, 10), 10)
    assert not fila.pode_enviar(config, estado, cliente, sabado)[0]
    assert fila.pode_enviar(config, estado, admin, sabado)[0]
    noite = quando(SEGUNDA, 22)
    pode, motivo, depois = fila.pode_enviar(config, estado, cliente, noite)
    assert not pode and "janela" in motivo and depois == quando(date(2026, 10, 6), 8)
    assert fila.pode_enviar(config, estado, cliente, quando(SEGUNDA, 10))[0]
    config.limite_hora = 1
    M.objects.create(empresa=empresa, telefone="5575911112222", status=M.Status.ENVIADA,
                     enviada_em=quando(SEGUNDA, 10) - timedelta(minutes=5))
    assert "hora" in fila.pode_enviar(config, estado, cliente, quando(SEGUNDA, 10))[1]


def test_intervalo_minimo_entre_mensagens(empresa, config, contato):
    estado = fila.estado_de(empresa)
    agora = quando(SEGUNDA, 10)
    M.objects.create(empresa=empresa, telefone="5575911112222", status=M.Status.ENVIADA, enviada_em=agora - timedelta(seconds=5))
    msg = fila.enfileirar(empresa, contato.telefone, "Olá", contato=contato)
    pode, motivo, depois = fila.pode_enviar(config, estado, msg, agora)
    assert not pode and depois == agora - timedelta(seconds=5) + timedelta(seconds=config.intervalo_min)


@freeze_time("2026-10-05 10:00:00-03:00")
def test_worker_envia_verifica_e_registra_primeiro_contato(empresa, config, contato):
    transporte = TransporteSimulado()
    msg = fila.enfileirar(empresa, contato.telefone, "Olá", contato=contato)
    espera = worker.passo(empresa, transporte, quando(SEGUNDA, 10))
    msg.refresh_from_db()
    contato.refresh_from_db()
    assert msg.status == M.Status.SIMULADA and transporte.enviados[0][2] == "Olá"
    assert contato.verificado and contato.jid and contato.primeira_mensagem_em
    assert espera >= config.intervalo_min - 0.01


@freeze_time("2026-10-05 10:00:00-03:00")
def test_falhas_reagendam_e_disjuntor_pausa(empresa, config, contato):
    class Quebrado(TransporteSimulado):
        def enviar_texto(self, destino, texto):
            raise ErroTransporte("desconectado")

    agora = quando(SEGUNDA, 10)
    msg = fila.enfileirar(empresa, contato.telefone, "m0", contato=contato)
    worker.passo(empresa, Quebrado(), agora)
    msg.refresh_from_db()
    assert msg.status == M.Status.PENDENTE and msg.agendada_para == agora + timedelta(minutes=2)  # backoff
    for _ in range(2):
        M.objects.filter(pk=msg.pk).update(agendada_para=agora)
        worker.passo(empresa, Quebrado(), agora)
    msg.refresh_from_db()
    assert msg.status == M.Status.FALHA and msg.tentativas == 3
    estado = EstadoSessao.objects.get(empresa=empresa)
    assert estado.falhas_seguidas == 3 and estado.pausado_ate > agora
    assert M.objects.filter(para_admin=True, texto__contains="pausados").exists()


def test_comandos_admin_e_confirmacao_de_lote(empresa, config, contato):
    respostas = comandos.processar(empresa, ADMIN, "ajuda", "wa-1")
    assert respostas and "comandos" in respostas[0].texto
    assert comandos.processar(empresa, ADMIN, "ajuda", "wa-1") == []  # mensagem repetida
    lote = envios._montar(empresa, "Teste", "MANUAL", [(contato, "Texto ao cliente", [])], True, config)
    assert lote.status == LoteEnvio.Status.AGUARDANDO
    assert M.objects.filter(lote=lote, status=M.Status.RETIDA).count() == 1
    codigo = Confirmacao.objects.get(objeto_id=str(lote.pk)).codigo
    comandos.processar(empresa, "557599990000", f"SIM {codigo}", "wa-2")  # admin sem o nono dígito
    lote.refresh_from_db()
    assert lote.status == LoteEnvio.Status.LIBERADO
    assert M.objects.filter(lote=lote, status=M.Status.PENDENTE).count() == 1


def test_cliente_sair_descadastra_e_cancela_pendentes(empresa, config, contato):
    fila.enfileirar(empresa, contato.telefone, "lembrete", contato=contato)
    comandos.processar(empresa, contato.telefone, "Sair", "wa-3")
    contato.refresh_from_db()
    assert contato.descadastrado_em and not contato.apto
    assert M.objects.get(texto="lembrete").status == M.Status.CANCELADA
    assert M.objects.filter(para_admin=True, texto__contains="pediu para não receber").exists()


def test_mensagem_livre_de_cliente_e_encaminhada_ao_admin(empresa, config, contato):
    assert comandos.processar(empresa, contato.telefone, "Recebi a nota, obrigado!", "wa-4") == []
    assert M.objects.filter(para_admin=True, texto__contains="Recebi a nota").exists()


def test_comandos_financeiros_respondem(empresa, config):
    for texto in ("financeiro", "previsao", "vencidos", "faturamento", "notas", "status", "pausar", "retomar", "xyz"):
        assert comandos.responder_admin(empresa, texto)[0], texto


def test_relatorio_xlsx(empresa, config):
    textos, anexos = comandos.responder_admin(empresa, "relatorio")
    assert anexos[0].nome.endswith(".xlsx") and anexos[0].tamanho > 1000


def _lancamento(pessoa, contrato, vencimento):
    categoria, _ = CategoriaFinanceira.objects.get_or_create(empresa=pessoa.empresa, nome="Contratos públicos",
                                                             defaults={"tipo": "RECEITA", "grupo_dre": "RECEITA_BRUTA"})
    return Lancamento.objects.create(empresa=pessoa.empresa, tipo="RECEITA", descricao="Parcela", pessoa=pessoa,
                                     categoria=categoria, centro_custo=centro_contrato(contrato), valor=Decimal("150"),
                                     data_competencia=vencimento, data_vencimento=vencimento, status="PENDENTE")


def test_lembretes_idempotentes_e_com_confirmacao(empresa, config, contato, contrato):
    hoje = date(2026, 10, 5)
    _lancamento(contato.pessoa, contrato, hoje + timedelta(days=3))
    _lancamento(contato.pessoa, contrato, hoje - timedelta(days=1))
    assert envios.lembretes(empresa, hoje) == 2
    assert envios.lembretes(empresa, hoje) == 0
    assert LoteEnvio.objects.filter(origem="LEMBRETE", status="AGUARDANDO").count() == 2
    textos = list(M.objects.filter(para_admin=False).values_list("texto", flat=True))
    assert any("vence em" in t for t in textos) and any("desconsidere" in t for t in textos)
    assert all("SAIR" in t for t in textos)


def test_envio_nota_sem_confirmacao_vai_para_fila(empresa, config, contato, monkeypatch):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed
    from apps.fiscal.models import NotaFiscal, PerfilFiscal

    reverse("faturamento:home")  # carrega as URLs antes de substituir garantir_pdf (evita vazar o falso)
    seed(empresa)
    config.confirmar_envios = False
    config.save()
    nota = NotaFiscal.objects.create(
        empresa=empresa, tomador=contato.pessoa, competencia=date(2026, 9, 1), numero_nfse="123",
        item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
        perfil=PerfilFiscal.objects.create(empresa=empresa, nome="P", aliquota_iss=Decimal("2")),
        valor_servicos=Decimal("10"), valor_liquido=Decimal("10"), discriminacao="x", status="AUTORIZADA",
        xml_autorizado=Anexo.criar(None, "nfse.xml", b"<x/>", empresa=empresa))
    monkeypatch.setattr("apps.fiscal.services.pdf_nfse.garantir_pdf",
                        lambda n: Anexo.criar(None, "nfse_123.pdf", b"%PDF", empresa=empresa))
    lote = envios.preparar_envio_nota(nota)
    assert envios.preparar_envio_nota(nota).pk == lote.pk  # não duplica
    assert lote.status == LoteEnvio.Status.LIBERADO
    nomes = sorted(M.objects.filter(lote=lote).exclude(nome_arquivo="").values_list("nome_arquivo", flat=True))
    assert nomes == ["nfse.xml", "nfse_123.pdf"]
    assert M.objects.filter(lote=lote, tipo="TEXTO", texto__contains="nº 123").exists()


def test_sem_consentimento_nao_envia(empresa, config, contato):
    contato.consentimento = False
    contato.save()
    assert envios.contatos_aptos(contato.pessoa, "nota") == []


def test_telas_whatsapp(cli, config, contato):
    for url in (reverse("whatsapp:home"), reverse("whatsapp:status"), reverse("whatsapp:configuracao"),
                reverse("whatsapp:contato_lista"), reverse("whatsapp:mensagem_lista"),
                reverse("cobranca:perfil", args=[contato.pessoa_id])):
        assert cli.get(url).status_code == 200, url
    assert cli.post(reverse("whatsapp:teste")).status_code == 302
    assert M.objects.filter(para_admin=True).exists()
    resposta = cli.post(reverse("whatsapp:contato_rapido", args=[contato.pessoa_id]), {
        "contato-nome": "João", "contato-telefone": "75 97777-2222", "contato-consentimento": "on",
        "contato-origem_consentimento": "E-mail 09/10/2026", "contato-recebe_notas": "on"})
    assert resposta.status_code == 302 and ContatoWhatsApp.objects.filter(telefone="5575977772222").exists()


def test_configuracao_valida_numeros(cli, config):
    dados = {f: getattr(config, f) for f in ("transporte", "horario_inicio", "horario_fim", "limite_hora", "limite_dia",
                                              "intervalo_min", "intervalo_max", "novos_por_dia", "prazo_confirmacao_h",
                                              "sem_resposta", "hora_lembretes", "hora_resumo")}
    dados.update({"ativo": "on", "numeros_admin": "abc", "horario_inicio": "08:00", "horario_fim": "19:00",
                  "hora_lembretes": "09:30", "hora_resumo": "08:00"})
    assert cli.post(reverse("whatsapp:configuracao"), dados).status_code == 200
    dados["numeros_admin"] = "(75) 99999-0000, 75 98888-0000"
    assert cli.post(reverse("whatsapp:configuracao"), dados).status_code == 302
    config.refresh_from_db()
    assert config.admins == ["5575999990000", "5575988880000"]
