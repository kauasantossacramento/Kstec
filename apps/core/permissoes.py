from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


def pode_escrever(user, papeis=None) -> bool:
    if not user.is_authenticated or user.somente_leitura:
        return False
    if not papeis:
        return True
    return user.tem_papel("Administrador", *papeis)


def exigir_escrita(user, papeis=None):
    if not pode_escrever(user, papeis):
        raise PermissionDenied("Seu papel não permite esta ação.")


class PapelMixin(LoginRequiredMixin):
    """Leitura liberada a autenticados; métodos de escrita exigem papel (Leitura nunca escreve)."""

    papeis_leitura: list[str] | None = None
    papeis_escrita: list[str] | None = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.papeis_leitura and not request.user.tem_papel("Administrador", "Leitura", *self.papeis_leitura):
            raise PermissionDenied
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            exigir_escrita(request.user, self.papeis_escrita)
        return super().dispatch(request, *args, **kwargs)
