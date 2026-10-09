"""Notificações in-app e por e-mail."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from ..models import Notificacao


def usuarios_com_papel(*papeis, empresa=None):
    User = get_user_model()
    qs = User.objects.filter(is_active=True)
    if empresa is not None:
        qs = qs.filter(empresa=empresa) | qs.filter(is_superuser=True, empresa__isnull=True)
    return (qs.filter(groups__name__in=papeis) | qs.filter(is_superuser=True)).distinct()


def notificar(usuarios, titulo, mensagem="", nivel="info", link="", email=False, chave_dedup="",
              janela_dedup_horas=20, empresa=None):
    """Cria notificação para cada usuário. `chave_dedup` evita repetir o mesmo alerta na janela."""
    criadas = []
    desde = timezone.now() - timedelta(hours=janela_dedup_horas)
    for u in usuarios:
        if chave_dedup and Notificacao.objects.filter(usuario=u, chave_dedup=chave_dedup, criado_em__gte=desde).exists():
            continue
        n = Notificacao(usuario=u, titulo=titulo[:200], mensagem=mensagem, nivel=nivel, link=link,
                        chave_dedup=chave_dedup, canal=Notificacao.Canal.EMAIL if email else Notificacao.Canal.APP)
        if empresa is not None:
            n.empresa = empresa
        elif u.empresa_id:
            n.empresa_id = u.empresa_id
        n.save()
        criadas.append(n)
        if email and u.email:
            corpo = mensagem + (f"\n\nAcesse: {settings.SITE_URL}{link}" if link else "")
            send_mail(f"[KS CENTRAL] {titulo}", corpo, settings.DEFAULT_FROM_EMAIL, [u.email], fail_silently=True)
    return criadas


def notificar_papeis(papeis, titulo, mensagem="", **kw):
    return notificar(usuarios_com_papel(*papeis, empresa=kw.get("empresa")), titulo, mensagem, **kw)
