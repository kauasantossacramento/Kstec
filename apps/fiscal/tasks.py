from celery import shared_task

from apps.core.models import Empresa


@shared_task
def sincronizar_respostas():
    """Lê a caixa de documentos e vincula respostas/devoluções aos e-mails enviados."""
    from apps.core import contexto

    from .services.caixa_email import sincronizar

    total = 0
    for empresa in Empresa.objects.all():
        with contexto.usar_contexto(empresa):
            total += sincronizar(empresa)
    return total
