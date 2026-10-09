from celery import shared_task

from .services import worker


@shared_task
def rotinas_whatsapp():
    """Expira confirmações, gera lembretes e o resumo diário. O envio em si é feito pelo whatsapp_worker."""
    return worker.periodicas_todas()
