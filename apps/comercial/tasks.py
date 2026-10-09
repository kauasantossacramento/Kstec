from celery import shared_task

from . import services


@shared_task
def expirar_orcamentos():
    return services.expirar_orcamentos()


@shared_task
def followup():
    return services.followup()
