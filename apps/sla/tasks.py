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
