"""Fila de saída e regras de ritmo que reduzem o risco de bloqueio do número.

Medidas aplicadas (clientes):
- só contatos com consentimento registrado, sem descadastro e com WhatsApp verificado;
- janela de horário e, opcionalmente, apenas dias úteis;
- limites por hora e por dia e cota diária de primeiras mensagens a contatos novos;
- intervalo aleatório entre mensagens e "digitando…" proporcional ao texto;
- disjuntor: falhas seguidas pausam a fila e avisam o administrador;
- deduplicação por chave e conteúdo variado (saudação por horário e variações de texto).
Mensagens ao administrador têm prioridade e ignoram janela/dias, mas mantêm intervalo mínimo.
"""

import random
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.validadores import normalizar_telefone

from ..models import ConfiguracaoWhatsApp, ContatoWhatsApp, EstadoSessao, MensagemWhatsApp

M = MensagemWhatsApp
LIMITE_ADMIN_HORA = 40
INTERVALO_ADMIN = 3
INTERVALO_MESMO_LOTE = (4, 10)


def config_de(empresa):
    config, _ = ConfiguracaoWhatsApp.objects.get_or_create(empresa=empresa)
    return config


def estado_de(empresa):
    estado, _ = EstadoSessao.objects.get_or_create(empresa=empresa)
    return estado


def mesmo_numero(a: str, b: str) -> bool:
    """Compara telefones BR tolerando o nono dígito (contas antigas usam JID sem ele)."""
    a, b = normalizar_telefone(a) or a, normalizar_telefone(b) or b
    if a == b:
        return True

    def sem_nove(n):
        return n[:4] + n[5:] if len(n) == 13 and n.startswith("55") and n[4] == "9" else n
    return sem_nove(a) == sem_nove(b)


def eh_admin(config, telefone):
    return any(mesmo_numero(telefone, adm) for adm in config.admins)


def enfileirar(empresa, telefone, texto="", *, anexo=None, nome_arquivo="", contato=None, lote=None, para_admin=False,
               chave="", status=None, agendada_para=None, ordem=0, prioridade=None):
    telefone = normalizar_telefone(telefone) or telefone
    if chave and M.objects.filter(empresa=empresa, chave=chave, telefone=telefone).exclude(
            status__in=[M.Status.CANCELADA, M.Status.FALHA]).exists():
        return None
    msg = M(empresa=empresa, telefone=telefone, texto=texto[:4000], anexo=anexo, nome_arquivo=nome_arquivo,
            contato=contato, lote=lote, para_admin=para_admin, chave=chave[:160], ordem=ordem,
            tipo=M.Tipo.DOCUMENTO if anexo else M.Tipo.TEXTO,
            status=status or M.Status.PENDENTE, agendada_para=agendada_para or timezone.now(),
            prioridade=prioridade or (M.Prioridade.ALTA if para_admin else M.Prioridade.NORMAL))
    msg.save()
    return msg


def para_admins(empresa, texto, anexos=(), chave=""):
    config = config_de(empresa)
    criadas = []
    for numero in config.admins:
        m = enfileirar(empresa, numero, texto, para_admin=True, chave=chave)
        if m is None:
            continue
        criadas.append(m)
        for i, anexo in enumerate(anexos, 1):
            criadas.append(enfileirar(empresa, numero, "", anexo=anexo, nome_arquivo=anexo.nome, para_admin=True,
                                      chave=f"{chave}:anexo:{anexo.pk}" if chave else "", ordem=i))
    return [c for c in criadas if c]


def saudacao(agora=None):
    hora = timezone.localtime(agora or timezone.now()).hour
    return "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"


def variar(*opcoes):
    return random.choice(opcoes)


# ---------------------------------------------------------------------------
# Ritmo
# ---------------------------------------------------------------------------

def na_janela(config, agora):
    local = timezone.localtime(agora)
    if config.dias_uteis and local.weekday() >= 5:
        return False
    return config.horario_inicio <= local.time() <= config.horario_fim


def proxima_janela(config, agora):
    local = timezone.localtime(agora)
    dia = local.date()
    for _ in range(8):
        inicio = timezone.make_aware(datetime.combine(dia, config.horario_inicio))
        if (not config.dias_uteis or dia.weekday() < 5) and inicio > agora:
            return inicio
        if (not config.dias_uteis or dia.weekday() < 5) and inicio <= agora <= timezone.make_aware(
                datetime.combine(dia, config.horario_fim)):
            return agora
        dia += timedelta(days=1)
    return agora + timedelta(hours=12)


def enviadas_desde(empresa, desde, admin=False):
    return M.objects.filter(empresa=empresa, direcao="SAIDA", para_admin=admin, enviada_em__gte=desde,
                            status__in=[M.Status.ENVIADA, M.Status.SIMULADA]).count()


def pode_enviar(config, estado, msg, agora):
    """Retorna (pode, motivo, reavaliar_em)."""
    if estado.pausado_ate and estado.pausado_ate > agora and not msg.para_admin:
        return False, f"fila pausada: {estado.motivo_pausa}", estado.pausado_ate
    ultima = M.objects.filter(empresa=msg.empresa, direcao="SAIDA", enviada_em__isnull=False).order_by("-enviada_em").first()
    if msg.para_admin:
        if enviadas_desde(msg.empresa, agora - timedelta(hours=1), admin=True) >= LIMITE_ADMIN_HORA:
            return False, "limite horário de mensagens ao administrador", agora + timedelta(minutes=5)
        if ultima and (agora - ultima.enviada_em).total_seconds() < INTERVALO_ADMIN:
            return False, "intervalo mínimo", ultima.enviada_em + timedelta(seconds=INTERVALO_ADMIN)
        return True, "", agora
    if not na_janela(config, agora):
        return False, "fora da janela de envio", proxima_janela(config, agora)
    if enviadas_desde(msg.empresa, agora - timedelta(hours=1)) >= config.limite_hora:
        return False, "limite por hora atingido", agora + timedelta(minutes=10)
    inicio_dia = timezone.make_aware(datetime.combine(timezone.localdate(agora), datetime.min.time()))
    if enviadas_desde(msg.empresa, inicio_dia) >= config.limite_dia:
        return False, "limite diário atingido", proxima_janela(config, inicio_dia + timedelta(days=1))
    if msg.contato_id and msg.contato.primeira_mensagem_em is None:
        novos = ContatoWhatsApp.objects.filter(empresa=msg.empresa, primeira_mensagem_em__gte=inicio_dia).count()
        if novos >= config.novos_por_dia:
            return False, "cota diária de contatos novos", proxima_janela(config, inicio_dia + timedelta(days=1))
    if ultima:
        mesmo_lote = msg.lote_id and ultima.lote_id == msg.lote_id and ultima.telefone == msg.telefone
        minimo = INTERVALO_MESMO_LOTE[0] if mesmo_lote else config.intervalo_min
        if (agora - ultima.enviada_em).total_seconds() < minimo:
            return False, "intervalo entre mensagens", ultima.enviada_em + timedelta(seconds=minimo)
    return True, "", agora


def intervalo_apos(config, msg, seguinte=None):
    """Pausa humana depois de um envio (o worker dorme este tempo)."""
    if msg.para_admin:
        return random.uniform(INTERVALO_ADMIN, INTERVALO_ADMIN + 3)
    if seguinte and seguinte.lote_id and seguinte.lote_id == msg.lote_id and seguinte.telefone == msg.telefone:
        return random.uniform(*INTERVALO_MESMO_LOTE)
    return random.uniform(config.intervalo_min, max(config.intervalo_min, config.intervalo_max))


def tempo_digitando(texto):
    return min(1.5 + len(texto or "") / random.uniform(14, 22), 8.0)


def proxima(empresa, agora=None):
    agora = agora or timezone.now()
    return M.objects.filter(empresa=empresa, direcao="SAIDA", status=M.Status.PENDENTE, agendada_para__lte=agora) \
        .select_related("contato", "anexo", "lote").order_by("prioridade", "agendada_para", "lote_id", "ordem", "criado_em").first()


@transaction.atomic
def reservar(msg):
    """Marca ENVIANDO de forma atômica; devolve None se outro processo já pegou."""
    alterados = M.objects.filter(pk=msg.pk, status=M.Status.PENDENTE).update(status=M.Status.ENVIANDO,
                                                                              tentativas=msg.tentativas + 1)
    if not alterados:
        return None
    msg.refresh_from_db()
    return msg


def adiar(msg, quando, motivo=""):
    M.objects.filter(pk=msg.pk).update(agendada_para=quando, erro=motivo[:300])


def pendentes_cliente(empresa):
    return M.objects.filter(empresa=empresa, direcao="SAIDA", para_admin=False).filter(
        Q(status=M.Status.PENDENTE) | Q(status=M.Status.RETIDA))
