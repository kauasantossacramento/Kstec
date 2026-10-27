"""UptimeRobot (API v2, chave somente leitura): referência externa de disponibilidade.

O monitor do KS CENTRAL verifica a partir de um único servidor: uma falha de rede entre servidores aparece como
queda mesmo com o sistema no ar. O UptimeRobot verifica de vários pontos e passa a ser a referência para o uptime
das telas, as barras diárias, o relatório de SLA e a confirmação de uma queda antes de alertar.
"""

from datetime import datetime, time, timedelta
from urllib.parse import urlparse

import httpx
from django.utils import timezone

from ..models import ConfiguracaoAlertas, Sistema

API = "https://api.uptimerobot.com/v2/getMonitors"
NO_AR, PARECE_FORA, FORA = 2, 8, 9
LOG_QUEDA = 1
STATUS = {0: "pausado", 1: "aguardando 1ª verificação", 2: "no ar", 8: "parece fora", 9: "fora do ar"}


class ErroUptimeRobot(Exception):
    pass


def configuracao(empresa):
    return ConfiguracaoAlertas.objects.filter(empresa=empresa).select_related("uptimerobot_chave").first()


def chave(empresa):
    config = configuracao(empresa)
    return config.uptimerobot_chave.ler() if config and config.uptimerobot_chave_id else ""


def consultar(api_key, transporte=None, **params):
    """getMonitors com paginação. Levanta ErroUptimeRobot em qualquer falha."""
    monitores, offset = [], 0
    try:
        with httpx.Client(timeout=20, transport=transporte, headers={"User-Agent": "KS-CENTRAL/1.0"}) as cli:
            while True:
                r = cli.post(API, data={"api_key": api_key, "format": "json", "offset": offset, "limit": 50, **params})
                r.raise_for_status()
                corpo = r.json()
                if corpo.get("stat") != "ok":
                    raise ErroUptimeRobot((corpo.get("error") or {}).get("message") or "resposta inválida do UptimeRobot")
                monitores += corpo.get("monitors") or []
                pag = corpo.get("pagination") or {}
                offset += int(pag.get("limit") or 50)
                if offset >= int(pag.get("total") or 0):
                    return monitores
    except httpx.HTTPStatusError as erro:
        raise ErroUptimeRobot(f"HTTP {erro.response.status_code} do UptimeRobot") from None
    except (httpx.HTTPError, ValueError) as erro:
        raise ErroUptimeRobot(f"Falha ao consultar o UptimeRobot: {type(erro).__name__}") from None


def normalizar(url):
    p = urlparse((url or "").strip().lower())
    host = (p.hostname or "").removeprefix("www.")
    return host + p.path.rstrip("/")


def _ts(dt):
    return int(dt.timestamp())


def _ratios(texto):
    return [float(x) for x in str(texto or "").split("-") if x.strip()]


def dias_recentes(dias=30, agora=None):
    """[(data, inicio, fim)] dos últimos `dias` dias locais; o dia de hoje vai até agora."""
    agora = agora or timezone.now()
    hoje = timezone.localdate(agora)
    saida = []
    for i in range(dias - 1, -1, -1):
        d = hoje - timedelta(days=i)
        ini = timezone.make_aware(datetime.combine(d, time.min))
        saida.append((d, ini, min(ini + timedelta(days=1) - timedelta(seconds=1), agora)))
    return saida


def sincronizar(empresa, transporte=None, agora=None):
    """Atualiza status, uptime 1/7/30 dias e uptime diário dos sistemas vinculados. Retorna quantos foram atualizados."""
    api_key = chave(empresa)
    if not api_key:
        return 0
    agora = agora or timezone.now()
    dias = dias_recentes(30, agora)
    try:
        monitores = consultar(api_key, transporte, custom_uptime_ratios="1-7-30",
                              custom_uptime_ranges="-".join(f"{_ts(i)}_{_ts(f)}" for _, i, f in dias))
    except ErroUptimeRobot as erro:
        ConfiguracaoAlertas.objects.filter(empresa=empresa).update(uptimerobot_erro=str(erro)[:300])
        return 0
    por_id = {str(m.get("id")): m for m in monitores}
    por_url = {normalizar(m.get("url")): m for m in monitores}
    total = 0
    for s in Sistema.objects.filter(empresa=empresa, ativo=True):
        m = por_id.get(s.uptimerobot_id) if s.uptimerobot_id else por_url.get(normalizar(s.url))
        if m is None:
            continue
        r1_7_30 = _ratios(m.get("custom_uptime_ratio"))
        diarios = _ratios(m.get("custom_uptime_ranges"))
        criado = int(m.get("create_datetime") or 0)
        Sistema.objects.filter(pk=s.pk).update(
            uptimerobot_id=str(m["id"]), ur_status=m.get("status"), ur_atualizado_em=agora,
            ur_uptimes=dict(zip(("1", "7", "30"), r1_7_30, strict=False)),
            ur_diario={d.isoformat(): v for (d, _, fim), v in zip(dias, diarios, strict=False) if _ts(fim) > criado})
        avisar_mudanca(s, s.ur_status, m.get("status"), agora)
        total += 1
    ConfiguracaoAlertas.objects.filter(empresa=empresa).update(uptimerobot_erro="")
    return total


def avisar_mudanca(sistema, anterior, novo, agora):
    """Queda/retorno vistos pela verificação externa quando o monitor local não acusou (ex.: falha regional,
    SSL ou conteúdo que só o UptimeRobot percebe). Se o local já marcou queda, o alerta dele basta."""
    if anterior is None or anterior == novo or sistema.em_manutencao or sistema.status == Sistema.Status.FORA:
        return
    caiu = anterior == NO_AR and novo in (PARECE_FORA, FORA)
    voltou = anterior in (PARECE_FORA, FORA) and novo == NO_AR
    if not (caiu or voltou):
        return
    from apps.core.services.notificacoes import notificar_papeis
    from apps.mensageria.services import alertas

    titulo = f"UptimeRobot: {sistema.nome} " + ("fora do ar" if caiu else "voltou")
    detalhe = ("A verificação externa (UptimeRobot) não alcança o sistema; o monitor do KS CENTRAL ainda responde."
               if caiu else "A verificação externa (UptimeRobot) voltou a alcançar o sistema.")
    chave = f"ur:{sistema.pk}:{novo}:{timezone.localtime(agora):%Y%m%d%H%M}"
    notificar_papeis(["Administrador", "Operação"], titulo, detalhe, nivel="danger" if caiu else "success",
                     empresa=sistema.empresa, link=f"/sla/sistemas/{sistema.pk}/", chave_dedup=chave)
    if sistema.alertar_whatsapp:
        alertas.monitoramento(sistema.empresa, ("🟠 *" if caiu else "🟢 *") + titulo + f"*\n{detalhe}\n{sistema.url}",
                              chave=chave)


def monitores(empresa, transporte=None):
    """Lista (para a tela de configuração) os monitores da conta e o sistema vinculado a cada um."""
    lista = consultar(chave(empresa), transporte, custom_uptime_ratios="30")
    sistemas = list(Sistema.objects.filter(empresa=empresa, ativo=True))
    for m in lista:
        m["sistema"] = next((s for s in sistemas if s.uptimerobot_id == str(m.get("id"))
                             or (not s.uptimerobot_id and normalizar(s.url) == normalizar(m.get("url")))), None)
        m["status_txt"] = STATUS.get(m.get("status"), "?")
        m["uptime30"] = (_ratios(m.get("custom_uptime_ratio")) or [None])[0]
    return lista


def status_atual(sistema, transporte=None):
    """Status do monitor agora (2 = no ar) ou None se não for possível consultar."""
    api_key = chave(sistema.empresa)
    if not (api_key and sistema.uptimerobot_id):
        return None
    try:
        lista = consultar(api_key, transporte, monitors=sistema.uptimerobot_id)
    except ErroUptimeRobot:
        return None
    return lista[0].get("status") if lista else None


def medir(sistema, inicio, fim, transporte=None):
    """Disponibilidade e quedas do período segundo o UptimeRobot, ou None sem vínculo/dados."""
    api_key = chave(sistema.empresa)
    if not (api_key and sistema.uptimerobot_id):
        return None
    fim = min(fim, timezone.now())
    try:
        lista = consultar(api_key, transporte, monitors=sistema.uptimerobot_id, logs=1,
                          custom_uptime_ranges=f"{_ts(inicio)}_{_ts(fim)}")
    except ErroUptimeRobot:
        return None
    if not lista:
        return None
    m = lista[0]
    criado = int(m.get("create_datetime") or 0)
    if criado >= _ts(fim):
        return None
    if criado > _ts(inicio):
        inicio = datetime.fromtimestamp(criado, tz=inicio.tzinfo)
    valores = _ratios(m.get("custom_uptime_ranges"))
    if not valores:
        return None
    uptime = valores[0]
    quedas = []
    for log in m.get("logs") or []:
        quando = int(log.get("datetime") or 0)
        if log.get("type") != LOG_QUEDA or not _ts(inicio) <= quando <= _ts(fim):
            continue
        ini = datetime.fromtimestamp(quando, tz=inicio.tzinfo)
        dur = int(log.get("duration") or 0)
        quedas.append({"inicio": timezone.localtime(ini).strftime("%d/%m %H:%M"),
                       "fim": timezone.localtime(ini + timedelta(seconds=dur)).strftime("%d/%m %H:%M"),
                       "minutos": round(dur / 60), "causa": ((log.get("reason") or {}).get("detail") or "")[:200]})
    quedas.reverse()  # a API devolve do mais recente para o mais antigo
    return {"uptime": round(uptime, 3), "inicio": inicio, "fim": fim, "incidentes": quedas,
            "indisponivel_seg": round((100 - uptime) / 100 * (fim - inicio).total_seconds()),
            "intervalo_min": max(int(m.get("interval") or 300) // 60, 1)}
