"""Alertas de queda/retorno por e-mail: destinatários gerais + por sistema e texto configurável."""

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from apps.core.services.email import enviar, lista_emails

from ..models import ConfiguracaoAlertas, Incidente


def configuracao(empresa):
    config, _ = ConfiguracaoAlertas.objects.get_or_create(empresa=empresa)
    return config


def contexto(sistema, evento, incidente=None):
    incidente = incidente or sistema.incidentes.order_by("-inicio").first()
    inicio = timezone.localtime(incidente.inicio) if incidente else timezone.localtime()
    duracao = (incidente.fim or timezone.now()) - incidente.inicio if incidente else timedelta()
    minutos = int(duracao.total_seconds() // 60)
    return {"sistema": sistema.nome, "url": sistema.url, "erro": sistema.ultimo_erro or "sem resposta",
            "inicio": f"{inicio:%d/%m/%Y %H:%M}", "status": sistema.get_status_display(),
            "duracao": f"{minutos // 60} h {minutos % 60:02d} min" if minutos >= 60 else f"{max(minutos, 1)} min",
            "contrato": sistema.contrato.numero if sistema.contrato_id else "",
            "cliente": str(sistema.contrato.cliente) if sistema.contrato_id else ""}


def renderizar(config, ctx, evento):
    valores = defaultdict(str, ctx)
    assunto = (config.assunto_queda if evento == "queda" else config.assunto_retorno).format_map(valores)
    corpo = (config.corpo_queda if evento == "queda" else config.corpo_retorno).format_map(valores)
    return assunto, corpo


def destinatarios(config, sistema):
    return lista_emails(sistema.emails_alerta, config.emails_gerais if sistema.incluir_gerais else "")


def enviar_alerta(sistema, evento):
    config = configuracao(sistema.empresa)
    if not (config.enviar_email and sistema.alertar_email):
        return 0
    destinos = destinatarios(config, sistema)
    if not destinos:
        return 0
    incidente = Incidente.objects.filter(sistema=sistema).order_by("-inicio").first()
    assunto, corpo = renderizar(config, contexto(sistema, evento, incidente), evento)
    return enviar("ALERTAS", assunto, corpo, destinos, empresa=sistema.empresa)


def exemplo(empresa):
    """Contexto fictício para a pré-visualização na tela."""
    from ..models import Sistema

    s = Sistema.objects.filter(empresa=empresa, ativo=True).select_related("contrato__cliente").first()
    agora = timezone.localtime()
    return {"sistema": s.nome if s else "Portal da Transparência", "url": s.url if s else "https://portal.exemplo.gov.br",
            "erro": "Sem resposta em 15s", "inicio": f"{agora:%d/%m/%Y %H:%M}", "duracao": "12 min", "status": "Fora do ar",
            "contrato": s.contrato.numero if s and s.contrato_id else "072/2026",
            "cliente": str(s.contrato.cliente) if s and s.contrato_id else "Prefeitura Municipal"}
