"""Envio de e-mail pelas contas configuradas na tela (Configurações → E-mails), com fallback para o settings.

Perfis local e de testes não usam as contas reais (EMAIL_CONTAS_SMTP=False): o envio segue o EMAIL_BACKEND do
perfil (console/locmem), para nunca disparar e-mail real durante desenvolvimento.
"""

import re

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from .. import contexto
from ..models import ContaEmail

SEPARADORES = re.compile(r"[;,\s]+")


def lista_emails(*textos):
    vistos, saida = set(), []
    for texto in textos:
        partes = texto if isinstance(texto, list | tuple) else SEPARADORES.split(texto or "")
        for e in partes:
            e = (e or "").strip().lower()
            if e and "@" in e and e not in vistos:
                vistos.add(e)
                saida.append(e)
    return saida


def conta(finalidade, empresa=None):
    empresa = empresa or contexto.empresa_atual()
    qs = ContaEmail.objects.filter(empresa=empresa, ativo=True, senha__isnull=False).select_related("senha")
    return qs.filter(finalidade=finalidade).first() or qs.first()


def conexao(finalidade, empresa=None):
    """Retorna (connection, from_email, bcc)."""
    c = conta(finalidade, empresa) if getattr(settings, "EMAIL_CONTAS_SMTP", True) else None
    if c is None:
        return get_connection(), settings.DEFAULT_FROM_EMAIL, []
    con = get_connection("django.core.mail.backends.smtp.EmailBackend", host=c.host, port=c.porta,
                         username=c.usuario or c.email, password=c.senha.ler(), use_ssl=c.seguranca == "SSL",
                         use_tls=c.seguranca == "STARTTLS", timeout=30, fail_silently=False)
    return con, c.remetente, [c.copia_para] if c.copia_para else []


def envio_real(finalidade, empresa=None):
    """True quando o envio sai de fato (conta SMTP cadastrada ou backend SMTP no settings)."""
    if getattr(settings, "EMAIL_CONTAS_SMTP", True) and conta(finalidade, empresa):
        return True
    return settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"


def enviar(finalidade, assunto, corpo, destinatarios, *, anexos=(), empresa=None, html=None):
    """Envia e devolve o número de mensagens aceitas pelo servidor. `anexos`: (nome, bytes, mimetype)."""
    destinos = lista_emails(destinatarios)
    if not destinos:
        return 0
    con, remetente, bcc = conexao(finalidade, empresa)
    msg = EmailMessage(assunto[:200], corpo, remetente, destinos, bcc=bcc, connection=con)
    if html:
        msg.content_subtype = "plain"
        msg.alternatives = [(html, "text/html")]
    for nome, conteudo, tipo in anexos:
        msg.attach(nome, conteudo, tipo)
    return msg.send(fail_silently=False)


def testar(conta_email, destino):
    try:
        enviado = enviar(conta_email.finalidade, "Teste de envio · KS CENTRAL",
                         f"Este é um teste da conta {conta_email.email} ({conta_email.get_finalidade_display()}).\n"
                         f"Enviado em {timezone.localtime():%d/%m/%Y %H:%M}.", [destino], empresa=conta_email.empresa)
    except Exception as erro:  # noqa: BLE001 — erro SMTP mostrado ao usuário.
        conta_email.ultimo_erro = str(erro)[:300]
        conta_email.save(update_fields=["ultimo_erro", "atualizado_em"])
        return False, conta_email.ultimo_erro
    conta_email.testado_em, conta_email.ultimo_erro = timezone.now(), ""
    conta_email.save(update_fields=["testado_em", "ultimo_erro", "atualizado_em"])
    return bool(enviado), "Mensagem aceita pelo servidor."
