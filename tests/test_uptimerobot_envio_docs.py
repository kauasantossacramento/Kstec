"""UptimeRobot como referência de disponibilidade e envio de documentos confirmado pelo WhatsApp."""

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.fernet import Fernet
from django.core import mail
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.certidoes.models import Certidao, TipoCertidao
from apps.core.models import Segredo
from apps.faturamento.models import AgendaFaturamento, CicloFaturamento
from apps.financeiro.services.custos import PARAMETROS, nova_planilha, salvar_planilha
from apps.fiscal.models import EntregaNota
from apps.fiscal.services import envio_documentos
from apps.mensageria.models import Confirmacao, MensagemWhatsApp
from apps.mensageria.services import confirmacoes, fila
from apps.operacao.relatorios import novo_relatorio
from apps.sla.models import Incidente, Sistema, Verificacao
from apps.sla.services import alertas_email, monitor, uptimerobot
from apps.sla.services import relatorio as sla
from tests.test_entregas_nfse import nota_autorizada as fixture_nota
from tests.test_entregas_nfse import pdf_minimo
from tests.test_entregas_nfse import pdf_rapido as fixture_pdf_rapido
from tests.test_fiscal_integrado import arquivo_a1 as fixture_a1
from tests.test_fiscal_integrado import preparado as fixture_preparado

arquivo_a1, preparado, nota_autorizada, pdf_rapido = fixture_a1, fixture_preparado, fixture_nota, fixture_pdf_rapido
ADMIN = "5575999990000"


# ---------------------------------------------------------------------------
# UptimeRobot
# ---------------------------------------------------------------------------

@pytest.fixture
def chave_ur(empresa, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    config = alertas_email.configuracao(empresa)
    config.uptimerobot_chave = Segredo.criar("UptimeRobot", "ur-teste", empresa=empresa)
    config.save()
    return config


@pytest.fixture
def sistema(empresa, contrato):
    return Sistema.objects.create(empresa=empresa, nome="Nuvem Municipal", url="https://nuvem.example.gov.br/",
                                  contrato=contrato, falhas_para_alerta=2, meta_sla=Decimal("99"))


def api_falsa(chamadas, status=2, ranges_por_dia="100.000", logs=()):
    def responder(request):
        dados = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        chamadas.append(dados)
        n = len(dados.get("custom_uptime_ranges", "").split("-")) if dados.get("custom_uptime_ranges") else 0
        monitor_ur = {"id": 801, "friendly_name": "nuvem", "url": "https://NUVEM.example.gov.br", "status": status,
                      "interval": 300, "create_datetime": 0, "custom_uptime_ratio": "100.000-100.000-99.990",
                      "custom_uptime_ranges": "-".join([ranges_por_dia] * n), "logs": list(logs)}
        return httpx.Response(200, json={"stat": "ok", "pagination": {"offset": 0, "limit": 50, "total": 1},
                                         "monitors": [monitor_ur]})
    return httpx.MockTransport(responder)


def test_sincronizar_vincula_por_endereco_e_vira_referencia(empresa, chave_ur, sistema):
    # O monitor local registrou uma falha de rede; o UptimeRobot não viu queda.
    Verificacao.objects.create(empresa=empresa, sistema=sistema, sucesso=False, erro="ConnectError")
    Verificacao.objects.create(empresa=empresa, sistema=sistema, sucesso=True)
    assert sistema.uptime(30) == 50.0
    chamadas = []
    assert uptimerobot.sincronizar(empresa, api_falsa(chamadas)) == 1
    s = Sistema.objects.get(pk=sistema.pk)
    assert chamadas[0]["api_key"] == "ur-teste" and chamadas[0]["custom_uptime_ratios"] == "1-7-30"
    assert s.uptimerobot_id == "801" and s.usa_uptimerobot and s.fonte_uptime == "UptimeRobot"
    assert s.uptime(30) == 99.99 and s.uptime(7) == 100.0
    barras = monitor.uptime_diario(s, 30)
    assert len(barras) == 30 and all(b["pct"] == 100.0 for b in barras)


def test_sem_chave_ou_api_fora_mantem_monitor_local(empresa, chave_ur, sistema):
    falha = httpx.MockTransport(lambda r: httpx.Response(200, json={"stat": "fail", "error": {"message": "api_key not found"}}))
    assert uptimerobot.sincronizar(empresa, falha) == 0
    chave_ur.refresh_from_db()
    assert "api_key" in chave_ur.uptimerobot_erro
    assert not Sistema.objects.get(pk=sistema.pk).usa_uptimerobot


def test_queda_so_local_nao_alerta_quando_uptimerobot_ve_no_ar(empresa, sistema, django_capture_on_commit_callbacks):
    config = fila.config_de(empresa)
    config.ativo, config.numeros_admin = True, ADMIN
    config.save()
    sistema.uptimerobot_id = "801"
    sistema.save()
    fora = httpx.MockTransport(lambda r: httpx.Response(503))
    consultas = []

    def no_ar(s):
        consultas.append(s.pk)
        return uptimerobot.NO_AR
    s = monitor.verificar(sistema, fora, externo=no_ar)
    assert consultas == []  # uma falha isolada nem consulta
    with django_capture_on_commit_callbacks(execute=True):
        s = monitor.verificar(s, fora, externo=no_ar)
    assert consultas and s.status != "FORA" and not Incidente.objects.exists()
    assert "UptimeRobot: no ar" in s.ultimo_erro
    assert Verificacao.objects.filter(sistema=s, sucesso=False, desconsiderada=True).count() == 2
    assert not MensagemWhatsApp.objects.filter(texto__contains="fora do ar").exists()
    # Quando o UptimeRobot também não alcança, é queda de verdade.
    with django_capture_on_commit_callbacks(execute=True):
        s = monitor.verificar(s, fora, externo=lambda _s: uptimerobot.FORA)
    assert s.status == "FORA" and Incidente.objects.filter(status="ABERTO").count() == 1


def test_falso_positivo_sai_do_uptime_e_do_sla(empresa, sistema):
    agora = timezone.now()
    for i in range(4):
        Verificacao.objects.create(empresa=empresa, sistema=sistema, sucesso=i == 0, em=agora - timedelta(minutes=20 - 5 * i))
    inc = Incidente.objects.create(empresa=empresa, sistema=sistema, inicio=agora - timedelta(minutes=10), fim=agora,
                                   status="FECHADO", causa="ConnectError")
    assert sistema.uptime(1) == 25.0
    with pytest.raises(Exception, match="falso positivo"):
        monitor.descartar_incidente(inc, "")
    monitor.descartar_incidente(inc, "UptimeRobot sem incidentes no período")
    inc.refresh_from_db()
    assert inc.status == "DESCARTADO" and "UptimeRobot sem incidentes" in inc.observacao
    assert sistema.uptime(1) == 100.0
    dados = sla.apurar(sistema.contrato, timezone.localdate())
    assert dados["sistemas"][0]["incidentes_qtd"] == 0 and dados["sistemas"][0]["uptime"] == 100.0


def test_sla_usa_uptimerobot_e_medicao_manual_prevalece(empresa, chave_ur, sistema):
    sistema.uptimerobot_id = "801"
    sistema.save()
    Verificacao.objects.create(empresa=empresa, sistema=sistema, sucesso=False)  # local: 0%
    queda = int((timezone.now() - timedelta(hours=2)).timestamp())
    chamadas = []
    transporte = api_falsa(chamadas, ranges_por_dia="99.950", logs=[
        {"type": 1, "datetime": queda, "duration": 600, "reason": {"code": "503", "detail": "Service Unavailable"}},
        {"type": 2, "datetime": queda + 600, "duration": 7200}])

    def medir(s, ini, fim):
        return uptimerobot.medir(s, ini, fim, transporte)
    dados = sla.apurar(sistema.contrato, timezone.localdate(), medir=medir)
    linha = dados["sistemas"][0]
    assert linha["origem"] == "uptimerobot" and linha["fonte"] == "UptimeRobot" and linha["uptime"] == 99.95
    assert linha["incidentes_qtd"] == 1 and linha["incidentes"][0]["minutos"] == 10
    assert chamadas[-1]["monitors"] == "801" and chamadas[-1]["logs"] == "1"
    manual = {str(sistema.pk): {"uptime": "100", "periodo_inicio": "2026-10-01", "periodo_fim": "2026-10-27"}}
    dados = sla.apurar(sistema.contrato, timezone.localdate(), manuais=manual, medir=medir)
    assert dados["sistemas"][0]["origem"] == "manual" and dados["sistemas"][0]["uptime"] == 100.0


def test_tela_uptimerobot_valida_e_guarda_chave_criptografada(cli, empresa, settings, sistema, monkeypatch):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    monkeypatch.setattr(uptimerobot, "consultar", lambda chave, transporte=None, **p: [
        {"id": 801, "url": "https://nuvem.example.gov.br", "status": 2, "custom_uptime_ratio": "100.000",
         "custom_uptime_ranges": "", "create_datetime": 0}])
    r = cli.post("/sla/uptimerobot/", {"acao": "salvar", "chave": "ur-chave-leitura"})
    assert r.status_code == 302
    config = alertas_email.configuracao(empresa)
    assert config.uptimerobot_chave.ler() == "ur-chave-leitura"
    assert bytes(config.uptimerobot_chave.valor_criptografado) != b"ur-chave-leitura"
    assert Sistema.objects.get(pk=sistema.pk).uptimerobot_id == "801"
    pagina = cli.get("/sla/uptimerobot/").content.decode()
    assert "Nuvem Municipal" in pagina and "ur-chave-leitura" not in pagina


# ---------------------------------------------------------------------------
# Envio de documentos confirmado no WhatsApp
# ---------------------------------------------------------------------------

@pytest.fixture
def cenario(nota_autorizada, contrato, admin_user, pdf_rapido, empresa):
    nota = nota_autorizada
    contrato.cliente = nota.tomador
    contrato.vigencia_inicio = date(2026, 5, 27)
    contrato.save()
    nota.contrato = contrato
    nota.save()
    tipo = TipoCertidao.objects.create(empresa=empresa, nome="CND Federal", orgao_emissor="Receita", esfera="FEDERAL")
    contrato.certidoes_exigidas.add(tipo)
    hoje = timezone.localdate()
    Certidao.objects.create(empresa=empresa, tipo=tipo, data_emissao=hoje - timedelta(days=5),
                            data_validade=hoje + timedelta(days=30), arquivo=ContentFile(pdf_minimo(), name="cnd.pdf"))
    rel = novo_relatorio(contrato, nota.competencia)
    rel.conteudo = "Atividades executadas na competência."
    rel.save()
    plan = nova_planilha(contrato, nota.competencia)
    dados = dict.fromkeys(PARAMETROS, Decimal(0)) | {"tributos": Decimal(6), "observacoes": "Base"}
    linhas = [{"grupo": "LICENCAS", "descricao": "Servidor", "unidade": "un", "quantidade": Decimal(1),
               "valor_unitario": Decimal(100), "rateio_pct": Decimal(100), "periodicidade": "MENSAL", "fonte": "Fatura"}]
    salvar_planilha(plan, dados, linhas, admin_user, aprovar=False)
    agenda = AgendaFaturamento.objects.create(
        empresa=empresa, contrato=contrato, item_catalogo=nota.item_catalogo, valor=Decimal("1"), dia_emissao=27,
        inicio=date(2026, 6, 1), referencia="MES_CORRENTE", enviar_email=True, emails_envio="dti@valenca.example.gov.br",
        assunto_envio="Para atesto — NFS-e {nota} — Contrato nº {contrato} — Competência {competencia}")
    ciclo = CicloFaturamento.objects.create(empresa=empresa, agenda=agenda, competencia=nota.competencia,
                                            data_emissao=hoje, data_vencimento=hoje + timedelta(days=30),
                                            valor=Decimal("1"), nota=nota)
    CicloFaturamento.objects.filter(pk=ciclo.pk).update(status="AUTORIZADO")
    config = fila.config_de(empresa)
    config.ativo, config.numeros_admin = True, ADMIN
    config.save()
    admin_user.telefone = "(75) 99999-0000"
    admin_user.save()
    return CicloFaturamento.objects.get(pk=ciclo.pk), rel, plan


def test_proposta_no_whatsapp_traz_corpo_e_anexos(cenario):
    ciclo, rel, plan = cenario
    c = envio_documentos.propor(ciclo)
    assert c is not None and c.acao == "fiscal.envio_documentos"
    assert set(c.dados["rascunhos"]) == {"relatorio", "planilha"}
    assert c.dados["assunto"].startswith(f"Para atesto — NFS-e {ciclo.nota.numero_nfse} — Contrato nº 012/2026")
    assert "5º mês de execução" in c.dados["mensagem"] and "DANFSe, relatório de atividades e demonstrativo de custos, assinados" in c.dados["mensagem"]
    msgs = MensagemWhatsApp.objects.filter(para_admin=True).order_by("ordem")
    texto = msgs.get(ordem=0).texto
    assert "Confirme o envio dos documentos" in texto and "dti@valenca.example.gov.br" in texto
    assert c.dados["mensagem"][:60] in texto and f"SIM {c.codigo}" in texto and "PRÉVIA" in texto
    nomes = [m.nome_arquivo for m in msgs.exclude(ordem=0)]
    assert len(nomes) == 4 and any(n.startswith("PREVIA_relatorio") for n in nomes) and any("certidao" in n for n in nomes)
    # Uma proposta por nota: a rotina não repete enquanto houver pedido pendente.
    assert envio_documentos.propor(ciclo) is None and envio_documentos.propor_pendentes() == 0


def test_sim_aprova_assina_e_envia_email(cenario, django_capture_on_commit_callbacks):
    ciclo, rel, plan = cenario
    c = envio_documentos.propor(ciclo)
    with django_capture_on_commit_callbacks(execute=True):
        _, resposta = confirmacoes.responder(ciclo.empresa, c.codigo, True, por=f"WhatsApp do administrador ({ADMIN})")
    assert "Aviso aqui quando concluir" in resposta
    rel.refresh_from_db()
    plan.refresh_from_db()
    assert rel.status == "APROVADO" and plan.status == "APROVADO" and rel.aprovado_por.telefone
    entrega = EntregaNota.objects.get(nota=ciclo.nota)
    assert entrega.status in ("SIMULADA", "ENVIADA") and entrega.destinatarios == ["dti@valenca.example.gov.br"]
    assert len(mail.outbox) == 1 and mail.outbox[0].subject == c.dados["assunto"]
    assert all(nome.endswith(".pdf") for nome, _, _ in mail.outbox[0].attachments)
    assert MensagemWhatsApp.objects.filter(texto__contains="E-mail enviado").exists()
    assert envio_documentos.propor(ciclo) is None  # já enviado


def test_nao_cancela_e_alteracao_apos_previa_bloqueia(cenario, django_capture_on_commit_callbacks):
    ciclo, rel, plan = cenario
    c = envio_documentos.propor(ciclo)
    _, resposta = confirmacoes.responder(ciclo.empresa, c.codigo, False)
    assert "não enviei" in resposta and not EntregaNota.objects.exists()
    assert envio_documentos.propor(ciclo) is None  # recusado: não insiste
    Confirmacao.objects.filter(pk=c.pk).delete()
    c = envio_documentos.propor(ciclo)
    rel.conteudo = "Texto alterado depois da prévia."
    rel.save()
    with django_capture_on_commit_callbacks(execute=True):
        confirmacoes.responder(ciclo.empresa, c.codigo, True)
    rel.refresh_from_db()
    assert rel.status == "RASCUNHO" and not EntregaNota.objects.exists() and not mail.outbox
    assert MensagemWhatsApp.objects.filter(texto__contains="alterado depois da prévia").exists()


def test_pendencias_avisam_sem_propor(cenario):
    ciclo, rel, plan = cenario
    rel.conteudo = ""
    rel.save()
    assert envio_documentos.propor(ciclo) is None
    aviso = MensagemWhatsApp.objects.get(para_admin=True)
    assert "Envio de documentos pendente" in aviso.texto and "sem conteúdo" in aviso.texto
    assert not Confirmacao.objects.filter(acao="fiscal.envio_documentos").exists()
    assert envio_documentos.propor(ciclo) is None and MensagemWhatsApp.objects.count() == 1  # sem repetir o aviso


def test_agenda_valida_destinatarios_e_campos_do_email(cenario):
    from apps.faturamento.forms import AgendaForm

    ciclo, _, _ = cenario
    agenda = ciclo.agenda
    base = {f: getattr(agenda, f) for f in ("item_catalogo", "valor", "referencia", "dia_emissao", "tipo_vencimento",
                                             "prazo_dias", "inicio", "modo")}
    base.update({"item_catalogo": agenda.item_catalogo_id, "hora_emissao": "08:00", "contrato": agenda.contrato_id,
                 "enviar_email": "on", "emails_envio": "nao-e-email", "assunto_envio": "NFS-e {nota}",
                 "mensagem_envio": "Segue {campo_inexistente}"})
    form = AgendaForm(base, instance=agenda)
    assert not form.is_valid()
    assert "emails_envio" in form.errors and "campo_inexistente" in str(form.errors["mensagem_envio"])


def test_telas_mostram_email_da_agenda_e_falso_positivo(cli, cenario, sistema, empresa):
    from django.urls import reverse

    ciclo, _, _ = cenario
    edicao = cli.get(reverse("faturamento:agenda_editar", args=[ciclo.agenda.pk])).content.decode()
    assert 'name="emails_envio"' in edicao and 'data-inserir="{anexos}"' in edicao
    assert "dti@valenca.example.gov.br" in cli.get(reverse("faturamento:agenda", args=[ciclo.agenda.pk])).content.decode()
    Incidente.objects.create(empresa=empresa, sistema=sistema, inicio=timezone.now(), fim=timezone.now(), status="FECHADO")
    detalhe = cli.get(reverse("sla:sistema_detalhe", args=[sistema.pk])).content.decode()
    assert "Marcar como falso positivo" in detalhe and "fonte: Monitor KS CENTRAL" in detalhe
