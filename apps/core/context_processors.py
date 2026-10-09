from django.conf import settings

from .menu import menu_para


def globais(request):
    ctx = {"SITE_URL": settings.SITE_URL, "empresa": getattr(request, "empresa", None)}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx.update(menu_para(request))
        ctx["notificacoes_nao_lidas"] = user.notificacoes.filter(lida_em__isnull=True).count()
        ctx["somente_leitura"] = user.somente_leitura
    return ctx
