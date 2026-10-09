from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from . import contexto

ROTAS_LIVRES = ("/health", "/static/", "/media/publico/", "/entrar", "/sair", "/mfa/", "/o/", "/status/",
                "/admin/login", "/api/")


class EmpresaMiddleware:
    """Define `request.empresa` e o contexto (empresa/usuário) para ModeloBase.save()."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        empresa = None
        if user is not None and user.is_authenticated and user.empresa_id:
            empresa = user.empresa
        if empresa is None:
            empresa = contexto.empresa_atual()
            if empresa is not None and user is not None and user.is_authenticated:
                user.empresa = empresa
                user.save(update_fields=["empresa"])
        request.empresa = empresa
        tokens = contexto.definir(empresa, user if user is not None and user.is_authenticated else None)
        try:
            return self.get_response(request)
        finally:
            contexto.limpar(tokens)


class MFAObrigatorioMiddleware:
    """Exige TOTP verificado para Administrador, Financeiro e Fiscal (seção 12)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            settings.MFA_OBRIGATORIO
            and user is not None
            and user.is_authenticated
            and not request.path.startswith(ROTAS_LIVRES)
            and user.exige_mfa
            and not user.is_verified()
        ):
            from django_otp.plugins.otp_totp.models import TOTPDevice

            if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
                return redirect(f"{reverse('core:mfa_verificar')}?next={request.get_full_path()}")
            return redirect("core:mfa_configurar")
        return self.get_response(request)


class CSPMiddleware:
    """Content-Security-Policy restritiva (seção 12). CDNs pinados apenas em jsdelivr."""

    POLITICA = "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ])

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/admin/"):
            response.setdefault("Content-Security-Policy", self.POLITICA)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response
