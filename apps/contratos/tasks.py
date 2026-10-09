from celery import shared_task

from . import services


@shared_task
def alertar_vigencia_saldo():
    return services.alertar_vigencia_saldo()


@shared_task
def gerar_competencias():
    return services.gerar_competencias_vigentes()
