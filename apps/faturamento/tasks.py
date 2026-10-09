"""Rotinas do beat. Cada uma usa trava distribuída para não rodar em paralelo entre workers."""

from celery import shared_task

from apps.core.travas import executar_com_trava

from .services import ciclos


@shared_task
def planejar_ciclos():
    return executar_com_trava("faturamento:planejar", ciclos.planejar_todas, ttl=1800)


@shared_task
def processar_ciclos():
    return executar_com_trava("faturamento:processar", ciclos.processar, ttl=1800)


@shared_task
def acompanhar_transmissoes():
    return executar_com_trava("faturamento:acompanhar", ciclos.acompanhar, ttl=900)
