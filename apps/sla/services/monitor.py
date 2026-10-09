"""Verificação dos sistemas, transição de estado, incidentes e alertas (app + WhatsApp)."""

import socket
import ssl
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from django.db import transaction
from django.utils import timezone

from apps.core.services.notificacoes import notificar_papeis

from ..models import Incidente, Sistema, Verificacao

S = Sistema.Status
RETENCAO_DIAS = 90


def checar(sistema, transporte=None):
    """Executa a requisição e devolve (sucesso, http_status, tempo_ms, erro). Não grava nada."""
    inicio = timezone.now()
    try:
        with httpx.Client(timeout=sistema.timeout_s, follow_redirects=True, transport=transporte,
                          headers={"User-Agent": "KS-CENTRAL-Monitor/1.0"}) as cli:
            resposta = cli.request(sistema.metodo, sistema.url)
        tempo = int((timezone.now() - inicio).total_seconds() * 1000)
    except httpx.TimeoutException:
        return False, None, None, f"Sem resposta em {sistema.timeout_s}s"
    except httpx.HTTPError as erro:
        return False, None, None, f"Falha de conexão: {type(erro).__name__}"
    if resposta.status_code != sistema.status_esperado:
        return False, resposta.status_code, tempo, f"HTTP {resposta.status_code} (esperado {sistema.status_esperado})"
    if sistema.palavra_chave and sistema.metodo == "GET" and sistema.palavra_chave not in resposta.text:
        return False, resposta.status_code, tempo, "Texto esperado não encontrado na página"
    return True, resposta.status_code, tempo, ""


def verificar(sistema, transporte=None, agora=None):
    agora = agora or timezone.now()
    sucesso, http, tempo, erro = checar(sistema, transporte)
    with transaction.atomic():
        s = Sistema.objects.select_for_update().get(pk=sistema.pk)
        Verificacao.objects.create(empresa=s.empresa, sistema=s, em=agora, sucesso=sucesso, http_status=http,
                                   tempo_ms=tempo, erro=erro[:300])
        anterior = s.status
        s.ultima_verificacao, s.ultimo_tempo_ms, s.ultimo_erro = agora, tempo, erro[:300]
        if sucesso:
            s.falhas_consecutivas = 0
            novo = S.DEGRADADO if tempo and tempo > s.lento_ms else S.OPERACIONAL
        else:
            s.falhas_consecutivas += 1
            # Uma falha isolada não muda o estado: só alerta após N falhas seguidas.
            novo = S.FORA if s.falhas_consecutivas >= s.falhas_para_alerta else anterior
        if s.em_manutencao:
            novo = S.MANUTENCAO
        mudou = novo != anterior
        if mudou:
            s.status, s.ultima_mudanca = novo, agora
        s.save()
        evento = None
        if mudou and novo == S.FORA:
            Incidente.objects.create(empresa=s.empresa, sistema=s, inicio=agora, causa=erro[:300])
            evento = "queda"
        elif mudou and anterior == S.FORA and novo in (S.OPERACIONAL, S.DEGRADADO):
            inc = s.incidentes.filter(status=Incidente.Status.ABERTO).first()
            if inc:
                inc.fim, inc.status = agora, Incidente.Status.FECHADO
                inc.save()
            evento = "retorno"
    if evento and not s.em_manutencao:
        transaction.on_commit(lambda: alertar(s, evento))
    return s


def duracao_texto(delta):
    minutos = int(delta.total_seconds() // 60)
    return f"{minutos // 60} h {minutos % 60} min" if minutos >= 60 else f"{max(minutos, 1)} min"


def alertar(sistema, evento):
    if evento == "queda":
        titulo, detalhe, nivel = f"{sistema.nome} fora do ar", sistema.ultimo_erro, "danger"
    else:
        inc = sistema.incidentes.filter(status=Incidente.Status.FECHADO).first()
        detalhe = f"Indisponível por {duracao_texto(inc.duracao)}." if inc else "Serviço restabelecido."
        titulo, nivel = f"{sistema.nome} voltou", "success"
    notificar_papeis(["Administrador", "Operação"], titulo, detalhe, nivel=nivel, empresa=sistema.empresa,
                     link=f"/sla/sistemas/{sistema.pk}/", chave_dedup=f"sla:{sistema.pk}:{evento}:{sistema.ultima_mudanca:%Y%m%d%H%M}")
    if sistema.alertar_whatsapp:
        from apps.mensageria.services import alertas

        alertas.sistema(sistema, evento == "queda", detalhe)
    try:
        from .alertas_email import enviar_alerta

        enviar_alerta(sistema, evento)
    except Exception:  # noqa: BLE001 — falha de SMTP não pode interromper o monitoramento.
        import logging

        logging.getLogger(__name__).exception("alerta por e-mail não enviado")


def vencidos(agora=None):
    agora = agora or timezone.now()
    for s in Sistema.objects.filter(ativo=True):
        if s.ultima_verificacao is None or s.ultima_verificacao + timedelta(minutes=s.intervalo_min) <= agora + timedelta(seconds=5):
            yield s


def despachar(agora=None):
    total = 0
    for s in list(vencidos(agora)):
        verificar(s, agora=agora)
        total += 1
    return total


def limpar(agora=None):
    limite = (agora or timezone.now()) - timedelta(days=RETENCAO_DIAS)
    return Verificacao.objects.filter(em__lt=limite).delete()[0]


def ssl_expiracao(url, timeout=10):
    parte = urlparse(url)
    if parte.scheme != "https":
        return None
    contexto = ssl.create_default_context()
    with socket.create_connection((parte.hostname, parte.port or 443), timeout=timeout) as sock:
        with contexto.wrap_socket(sock, server_hostname=parte.hostname) as tls:
            validade = tls.getpeercert()["notAfter"]
    return datetime.strptime(validade, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)


def verificar_ssl_todos():
    total = 0
    for s in Sistema.objects.filter(ativo=True, url__startswith="https://"):
        try:
            expira = ssl_expiracao(s.url)
        except (OSError, ssl.SSLError, ValueError, KeyError):
            continue
        Sistema.objects.filter(pk=s.pk).update(ssl_expira_em=expira)
        if expira and expira - timezone.now() < timedelta(days=15):
            notificar_papeis(["Administrador"], f"Certificado SSL de {s.nome} vence em breve",
                             f"Expira em {timezone.localtime(expira):%d/%m/%Y}.", nivel="warning", empresa=s.empresa,
                             chave_dedup=f"ssl:{s.pk}:{expira:%Y%m%d}", janela_dedup_horas=24 * 7)
        total += 1
    return total


def uptime_diario(sistema, dias=30):
    """Lista {dia, pct} para o componente uptime_bar."""
    hoje = timezone.localdate()
    inicio = hoje - timedelta(days=dias - 1)
    por_dia = {}
    for v in sistema.verificacoes.filter(em__date__gte=inicio).only("em", "sucesso"):
        d = timezone.localtime(v.em).date()
        total, ok = por_dia.get(d, (0, 0))
        por_dia[d] = (total + 1, ok + (1 if v.sucesso else 0))
    saida = []
    for i in range(dias):
        d = inicio + timedelta(days=i)
        total, ok = por_dia.get(d, (0, 0))
        saida.append({"dia": d, "pct": round(100 * ok / total, 2) if total else None})
    return saida
