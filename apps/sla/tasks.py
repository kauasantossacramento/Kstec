from celery import shared_task

from apps.core.travas import executar_com_trava

from .services import monitor


@shared_task
def despachar_verificacoes():
    return executar_com_trava("sla:despachar", monitor.despachar, ttl=300)


@shared_task
def limpar_brutos():
    return monitor.limpar()


@shared_task
def verificar_ssl_todos():
    return monitor.verificar_ssl_todos()


@shared_task
def sincronizar_uptimerobot():
    """Uptime 1/7/30 dias, barras diárias e status dos sistemas vinculados ao UptimeRobot."""
    from apps.core import contexto
    from apps.core.models import Empresa

    from .services.uptimerobot import sincronizar

    total = 0
    for empresa in Empresa.objects.all():
        with contexto.usar_contexto(empresa):
            total += sincronizar(empresa)
    return total
