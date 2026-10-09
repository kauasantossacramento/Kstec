from celery import shared_task

from . import services


@shared_task
def alertar_vencimentos():
    return services.alertar_vencimentos()
