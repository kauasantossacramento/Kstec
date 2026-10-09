from celery import shared_task

from .services.lancamentos import marcar_atrasados as executar


@shared_task
def marcar_atrasados():
    return executar()


@shared_task
def gerar_recorrencias():
    from .models import Recorrencia
    from .services.recorrencias import gerar

    return sum(gerar(obj) for obj in Recorrencia.objects.filter(ativo=True))
