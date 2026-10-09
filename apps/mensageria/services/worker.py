"""Lógica do worker do WhatsApp, independente do transporte (testável com TransporteSimulado)."""

import base64
import io
import logging
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.utils import timezone

from apps.core import contexto
from apps.core.travas import executar_com_trava

from ..models import ContatoWhatsApp, EstadoSessao, MensagemWhatsApp
from . import comandos, confirmacoes, envios, fila
from .transporte import ErroTransporte

log = logging.getLogger(__name__)
M = MensagemWhatsApp
MAX_TENTATIVAS = 3
FALHAS_PARA_PAUSAR = 3
PAUSA_DISJUNTOR = timedelta(minutes=30)


def atualizar_estado(empresa, estado, qr=None, conta=None, detalhe=None):
    with contexto.usar_contexto(empresa):
        close_old_connections()
        obj = fila.estado_de(empresa)
        obj.estado = estado
        if qr is not None:
            obj.qr = qr
            obj.qr_em = timezone.now()
        if estado == EstadoSessao.Estado.CONECTADO:
            obj.qr = ""
        if conta is not None:
            obj.conta = conta[:60]
        if detalhe is not None:
            obj.detalhe = detalhe[:300]
        obj.batimento = timezone.now()
        obj.save()


def batimento(empresa):
    EstadoSessao.objects.filter(empresa=empresa).update(batimento=timezone.now())


def qr_png(texto):
    """QR Code em data URI PNG para exibir na tela de conexão."""
    import qrcode

    buf = io.BytesIO()
    qrcode.make(texto, box_size=8, border=2).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def receber(empresa, telefone, texto, wa_id):
    with contexto.usar_contexto(empresa):
        close_old_connections()
        comandos.processar(empresa, telefone, texto, wa_id)


def _destino(msg, transporte):
    contato = msg.contato
    if contato and contato.jid:
        return contato.jid
    ok, jid = transporte.verificar(msg.telefone)
    if contato:
        ContatoWhatsApp.objects.filter(pk=contato.pk).update(verificado=ok, jid=jid)
    return jid if ok else None


def _falhar(empresa, msg, erro, agora):
    msg.erro = str(erro)[:300]
    if msg.tentativas >= MAX_TENTATIVAS:
        msg.status = M.Status.FALHA
    else:
        msg.status = M.Status.PENDENTE
        msg.agendada_para = agora + timedelta(minutes=2 ** msg.tentativas)
    msg.save(update_fields=["erro", "status", "agendada_para", "atualizado_em"])
    with transaction.atomic():
        estado = EstadoSessao.objects.select_for_update().get(empresa=empresa)
        estado.falhas_seguidas += 1
        disparou = estado.falhas_seguidas >= FALHAS_PARA_PAUSAR and not (estado.pausado_ate and estado.pausado_ate > agora)
        if disparou:
            estado.pausado_ate = agora + PAUSA_DISJUNTOR
            estado.motivo_pausa = f"{estado.falhas_seguidas} falhas seguidas"
        estado.save()
    if disparou:
        fila.para_admins(empresa, f"⚠️ Envios a clientes pausados por 30 min após {FALHAS_PARA_PAUSAR} falhas seguidas.\n"
                                  f"Último erro: {msg.erro[:150]}", chave=f"disjuntor:{agora:%Y%m%d%H%M}")


def passo(empresa, transporte, agora=None):
    """Processa no máximo uma mensagem. Retorna quantos segundos o worker deve aguardar."""
    agora = agora or timezone.now()
    config = fila.config_de(empresa)
    if not config.ativo:
        return 15
    if not transporte.pronto():
        return 5
    msg = fila.proxima(empresa, agora)
    if msg is None:
        return 3
    pode, motivo, quando = fila.pode_enviar(config, fila.estado_de(empresa), msg, agora)
    if not pode:
        espera = (quando - agora).total_seconds()
        if espera > 5:
            fila.adiar(msg, quando, motivo)
        return min(max(espera, 1), 30)
    msg = fila.reservar(msg)
    if msg is None:
        return 0.5
    try:
        destino = _destino(msg, transporte)
        if destino is None:
            msg.status, msg.erro = M.Status.FALHA, "Número sem WhatsApp."
            msg.save(update_fields=["status", "erro", "atualizado_em"])
            if msg.para_admin:
                log.warning("número de administrador sem WhatsApp: final %s", msg.telefone[-4:])
            return 1
        if msg.tipo == M.Tipo.TEXTO:
            if config.simular_digitacao:
                transporte.digitando(destino, fila.tempo_digitando(msg.texto))
            wa_id = transporte.enviar_texto(destino, msg.texto)
        else:
            wa_id = transporte.enviar_documento(destino, msg.anexo.ler(), msg.nome_arquivo or msg.anexo.nome, msg.texto)
    except (ErroTransporte, OSError) as erro:
        _falhar(empresa, msg, erro, agora)
        return 10
    msg.status = M.Status.SIMULADA if transporte.simulado else M.Status.ENVIADA
    msg.enviada_em, msg.wa_id, msg.erro = timezone.now(), str(wa_id or "")[:80], ""
    msg.save(update_fields=["status", "enviada_em", "wa_id", "erro", "atualizado_em"])
    if msg.contato_id and msg.contato.primeira_mensagem_em is None:
        ContatoWhatsApp.objects.filter(pk=msg.contato_id, primeira_mensagem_em__isnull=True).update(
            primeira_mensagem_em=timezone.now())
    EstadoSessao.objects.filter(empresa=empresa).update(falhas_seguidas=0)
    envios.concluir_se_terminou(msg.lote_id)
    return fila.intervalo_apos(config, msg, fila.proxima(empresa))


# ---------------------------------------------------------------------------
# Rotinas periódicas (worker a cada 5 min e Celery beat a cada 10 min; idempotentes)
# ---------------------------------------------------------------------------

def resumo_diario(empresa, agora=None):
    config = fila.config_de(empresa)
    agora = timezone.localtime(agora or timezone.now())
    if not (config.ativo and config.resumo_diario and config.admins) or agora.time() < config.hora_resumo:
        return 0
    partes = []
    for funcao in (comandos.cmd_financeiro, comandos.cmd_faturamento, comandos.cmd_status):
        try:
            partes.append(funcao(empresa)[0][0])
        except Exception:  # noqa: BLE001 — um bloco indisponível não impede o resumo.
            continue
    texto = f"☀️ *Resumo de {agora:%d/%m}*\n\n" + "\n\n".join(partes)
    return len(fila.para_admins(empresa, texto, chave=f"resumo:{agora:%Y%m%d}"))


def periodicas(empresa, agora=None):
    agora = agora or timezone.now()
    config = fila.config_de(empresa)
    if not config.ativo:
        return {}
    with contexto.usar_contexto(empresa):
        saida = {"expiradas": confirmacoes.expirar(empresa, agora), "resumo": resumo_diario(empresa, agora)}
        local = timezone.localtime(agora)
        if local.time() >= config.hora_lembretes and fila.na_janela(config, agora):
            saida["lembretes"] = envios.lembretes(empresa, local.date())
        # Mensagens que ficaram presas em ENVIANDO (queda do processo) voltam para a fila.
        M.objects.filter(empresa=empresa, status=M.Status.ENVIANDO, atualizado_em__lt=agora - timedelta(minutes=10)) \
            .update(status=M.Status.PENDENTE, erro="retomada após interrupção do worker")
    return saida


def periodicas_todas():
    from ..models import ConfiguracaoWhatsApp

    return {str(c.empresa_id): executar_com_trava(f"whatsapp:rotinas:{c.empresa_id}", periodicas, c.empresa, ttl=600)
            for c in ConfiguracaoWhatsApp.objects.filter(ativo=True).select_related("empresa")}
