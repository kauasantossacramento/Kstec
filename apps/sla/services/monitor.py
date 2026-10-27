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
        return False, None, None, descrever_erro(erro)
    if resposta.status_code != sistema.status_esperado:
        return False, resposta.status_code, tempo, f"HTTP {resposta.status_code} (esperado {sistema.status_esperado})"
    if sistema.palavra_chave and sistema.metodo == "GET" and sistema.palavra_chave not in resposta.text:
        return False, resposta.status_code, tempo, "Texto esperado não encontrado na página"
    return True, resposta.status_code, tempo, ""


MOTIVOS_SSL = [("expired", "certificado expirado"), ("hostname mismatch", "certificado não corresponde ao domínio"),
               ("doesn't match", "certificado não corresponde ao domínio"), ("self-signed", "certificado autoassinado"),
               ("self signed", "certificado autoassinado"), ("local issuer", "cadeia de certificados incompleta"),
               ("not yet valid", "certificado ainda não válido")]
MOTIVOS_REDE = [("name or service not known", "domínio não resolve (DNS)"), ("nodename nor servname", "domínio não resolve (DNS)"),
                ("temporary failure in name resolution", "falha de DNS"), ("connection refused", "conexão recusada"),
                ("network is unreachable", "rede inalcançável"), ("no route to host", "sem rota até o servidor"),
                ("connection reset", "conexão interrompida pelo servidor")]
PREFIXO_SSL = "Certificado SSL inválido"
PREFIXOS_REDE = ("Falha de conexão", "Sem resposta")


def descrever_erro(erro):
    """Texto do erro de rede: certificado SSL (com o motivo) separado de falhas de conexão/DNS."""
    texto = str(erro).lower()
    if "certificate" in texto or "ssl" in texto:
        motivo = next((m for chave, m in MOTIVOS_SSL if chave in texto), "falha na validação do certificado")
        return f"{PREFIXO_SSL}: {motivo}"
    motivo = next((m for chave, m in MOTIVOS_REDE if chave in texto), "")
    return f"Falha de conexão: {motivo or type(erro).__name__}"


def falha_de_rede(erro):
    """Falhas que podem ser só do caminho entre os servidores (as que o UptimeRobot pode desmentir)."""
    return (erro or "").startswith(PREFIXOS_REDE)


def lentidao(sistema, n):
    """True/False quando as últimas `n` verificações (incluindo esta) foram todas lentas/rápidas; None se misturadas."""
    ultimas = list(sistema.verificacoes.order_by("-em").values_list("sucesso", "tempo_ms")[:n])
    if len(ultimas) < n or not all(ok for ok, _ in ultimas):
        return None
    lentas = [bool(t and t > sistema.lento_ms) for _, t in ultimas]
    return True if all(lentas) else False if not any(lentas) else None


def confirmar_externo(sistema):
    from .uptimerobot import status_atual

    return status_atual(sistema)


def verificar(sistema, transporte=None, agora=None, externo=None):
    """`externo`: função que devolve o status do UptimeRobot (padrão: consulta a API) usada para confirmar a queda."""
    agora = agora or timezone.now()
    sucesso, http, tempo, erro = checar(sistema, transporte)
    no_ar_externo = False
    if not sucesso and falha_de_rede(erro) and sistema.uptimerobot_id and sistema.status != S.FORA \
            and sistema.falhas_consecutivas + 1 >= sistema.falhas_para_alerta:
        from .uptimerobot import NO_AR

        # Consulta externa fora da transação: só vira queda se o UptimeRobot também não alcançar o sistema.
        no_ar_externo = (externo or confirmar_externo)(sistema) == NO_AR
        if no_ar_externo:
            erro = f"{erro} · UptimeRobot: no ar (falha só a partir do servidor de monitoramento)"
    with transaction.atomic():
        s = Sistema.objects.select_for_update().get(pk=sistema.pk)
        Verificacao.objects.create(empresa=s.empresa, sistema=s, em=agora, sucesso=sucesso, http_status=http,
                                   tempo_ms=tempo, erro=erro[:300], desconsiderada=no_ar_externo)
        if no_ar_externo:
            ultimo_ok = s.verificacoes.filter(sucesso=True).order_by("-em").values_list("em", flat=True).first()
            s.verificacoes.filter(sucesso=False, desconsiderada=False, **({"em__gt": ultimo_ok} if ultimo_ok else {})) \
                .update(desconsiderada=True)
        anterior = s.status
        s.ultima_verificacao, s.ultimo_tempo_ms, s.ultimo_erro = agora, tempo, erro[:300]
        if sucesso:
            s.falhas_consecutivas = 0
            if anterior in (S.OPERACIONAL, S.DEGRADADO):
                # Lentidão (e sua normalização) só muda o estado após N verificações seguidas no mesmo sentido.
                seguidas = lentidao(s, s.falhas_para_alerta)
                novo = S.DEGRADADO if seguidas is True else S.OPERACIONAL if seguidas is False else anterior
            else:
                novo = S.DEGRADADO if tempo and tempo > s.lento_ms else S.OPERACIONAL
        else:
            s.falhas_consecutivas += 1
            # Uma falha isolada não muda o estado: só alerta após N falhas seguidas (e, com UptimeRobot, se ele confirmar).
            novo = S.FORA if s.falhas_consecutivas >= s.falhas_para_alerta and not no_ar_externo else anterior
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
        elif mudou and anterior == S.OPERACIONAL and novo == S.DEGRADADO:
            evento = "lento"
        elif mudou and anterior == S.DEGRADADO and novo == S.OPERACIONAL:
            evento = "normalizado"
    if evento and not s.em_manutencao:
        transaction.on_commit(lambda: alertar(s, evento))
    return s


def duracao_texto(delta):
    minutos = int(delta.total_seconds() // 60)
    return f"{minutos // 60} h {minutos % 60} min" if minutos >= 60 else f"{max(minutos, 1)} min"


def alertar_desempenho(sistema, evento):
    """Lentidão e normalização: aviso interno e WhatsApp do administrador (não vai por e-mail ao cliente)."""
    from apps.mensageria.services import alertas

    if evento == "lento":
        titulo = f"{sistema.nome} lento"
        detalhe = (f"Resposta de {sistema.ultimo_tempo_ms} ms nas últimas {sistema.falhas_para_alerta} verificações "
                   f"(limite {sistema.lento_ms} ms).")
        texto, nivel = f"🟡 *{titulo}*\n{detalhe}\n{sistema.url}", "warning"
    else:
        titulo, detalhe = f"{sistema.nome} normalizado", f"Tempo de resposta voltou ao normal ({sistema.ultimo_tempo_ms} ms)."
        texto, nivel = f"🟢 *{titulo}*\n{detalhe}", "success"
    chave = f"sla:{sistema.pk}:{evento}:{sistema.ultima_mudanca:%Y%m%d%H%M}"
    notificar_papeis(["Administrador", "Operação"], titulo, detalhe, nivel=nivel, empresa=sistema.empresa,
                     link=f"/sla/sistemas/{sistema.pk}/", chave_dedup=chave)
    if sistema.alertar_whatsapp:
        alertas.monitoramento(sistema.empresa, texto, chave=chave)


def alertar(sistema, evento):
    if evento in ("lento", "normalizado"):
        return alertar_desempenho(sistema, evento)
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


AVISAR_SSL_DIAS = {30, 15, 7, 3}


def verificar_ssl_todos(agora=None, consultar=None):
    """Diário: validade do certificado. Avisa no WhatsApp com 30, 15, 7 e 3 dias e todo dia nos 2 últimos; e
    também se o certificado já estiver inválido (expirado, domínio errado, cadeia incompleta)."""
    from apps.mensageria.services import alertas

    agora = agora or timezone.now()
    total = 0
    for s in Sistema.objects.filter(ativo=True, em_manutencao=False, url__startswith="https://"):
        try:
            expira = (consultar or ssl_expiracao)(s.url)
        except ssl.SSLError as erro:
            motivo = descrever_erro(erro)
            chave = f"ssl-invalido:{s.pk}:{timezone.localdate(agora):%Y%m%d}"
            notificar_papeis(["Administrador", "Operação"], f"{s.nome}: certificado SSL inválido", motivo, nivel="danger",
                             empresa=s.empresa, link=f"/sla/sistemas/{s.pk}/", chave_dedup=chave)
            if s.alertar_whatsapp:
                alertas.monitoramento(s.empresa, f"🔐 *{s.nome}: certificado SSL inválido*\n{motivo}\n{s.url}", chave=chave)
            continue
        except (OSError, ValueError, KeyError):
            continue
        Sistema.objects.filter(pk=s.pk).update(ssl_expira_em=expira)
        total += 1
        if not expira:
            continue
        dias = (expira - agora).days
        if dias < 15:
            notificar_papeis(["Administrador"], f"Certificado SSL de {s.nome} vence em breve",
                             f"Expira em {timezone.localtime(expira):%d/%m/%Y}.", nivel="warning", empresa=s.empresa,
                             chave_dedup=f"ssl:{s.pk}:{expira:%Y%m%d}", janela_dedup_horas=24 * 7)
        if s.alertar_whatsapp and (dias in AVISAR_SSL_DIAS or dias <= 2):
            quando = "vence hoje" if dias <= 0 else "vence amanhã" if dias == 1 else f"vence em {dias} dias"
            alertas.monitoramento(s.empresa, f"🔐 *Certificado SSL de {s.nome} {quando}*\n"
                                             f"Validade: {timezone.localtime(expira):%d/%m/%Y %H:%M}\n{s.url}",
                                  chave=f"ssl-vence:{s.pk}:{timezone.localdate(agora):%Y%m%d}")
    return total


def uptime_diario(sistema, dias=30):
    """Lista {dia, pct} para o componente uptime_bar (UptimeRobot quando sincronizado; senão o monitor local)."""
    hoje = timezone.localdate()
    inicio = hoje - timedelta(days=dias - 1)
    if sistema.usa_uptimerobot and sistema.ur_diario:
        return [{"dia": d, "pct": sistema.ur_diario.get(d.isoformat())}
                for d in (inicio + timedelta(days=i) for i in range(dias))]
    por_dia = {}
    for v in sistema.verificacoes.filter(em__date__gte=inicio, desconsiderada=False).only("em", "sucesso"):
        d = timezone.localtime(v.em).date()
        total, ok = por_dia.get(d, (0, 0))
        por_dia[d] = (total + 1, ok + (1 if v.sucesso else 0))
    saida = []
    for i in range(dias):
        d = inicio + timedelta(days=i)
        total, ok = por_dia.get(d, (0, 0))
        saida.append({"dia": d, "pct": round(100 * ok / total, 2) if total else None})
    return saida


def descartar_incidente(incidente, motivo, usuario=None):
    """Falso positivo (falha do próprio monitor): o incidente e as falhas do período saem do uptime e do SLA."""
    from django.core.exceptions import ValidationError

    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        raise ValidationError("Explique em poucas palavras por que é um falso positivo.")
    with transaction.atomic():
        inc = Incidente.objects.select_for_update().select_related("sistema").get(pk=incidente.pk)
        if inc.status == Incidente.Status.DESCARTADO:
            return inc
        s = inc.sistema
        margem = timedelta(minutes=s.intervalo_min * (s.falhas_para_alerta + 1))
        s.verificacoes.filter(sucesso=False, em__gte=inc.inicio - margem, em__lte=inc.fim or timezone.now()) \
            .update(desconsiderada=True)
        inc.fim = inc.fim or timezone.now()
        inc.status = Incidente.Status.DESCARTADO
        quem = f" ({usuario})" if getattr(usuario, "pk", None) else ""
        inc.observacao = (inc.observacao + "\n" if inc.observacao else "") + \
            f"Falso positivo em {timezone.localtime():%d/%m/%Y %H:%M}{quem}: {motivo}"
        inc.save()
    return inc
