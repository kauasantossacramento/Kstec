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


@shared_task
def propor_envios_documentos():
    """Envia ao WhatsApp, para confirmação, o e-mail de documentos das notas autorizadas recentes."""
    from apps.core import contexto

    from .services.envio_documentos import propor_pendentes

    total = 0
    for empresa in Empresa.objects.all():
        with contexto.usar_contexto(empresa):
            total += propor_pendentes()
    return total


@shared_task(soft_time_limit=280, time_limit=300)
def executar_envio_documentos(confirmacao_pk):
    """Após o SIM no WhatsApp: aprova rascunhos, monta o pacote e envia o e-mail."""
    from apps.core import contexto
    from apps.mensageria.models import Confirmacao

    from .services.envio_documentos import executar

    c = Confirmacao.objects.select_related("empresa").filter(pk=confirmacao_pk).first()
    if c is None:
        return None
    with contexto.usar_contexto(c.empresa):
        return executar(confirmacao_pk)
