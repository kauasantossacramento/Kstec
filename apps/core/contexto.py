"""Contexto da requisição/tarefa corrente (empresa e usuário) via contextvars.

Permite que `ModeloBase.save()` preencha `empresa` e `criado_por` sem que cada view
precise repassá-los, inclusive dentro de tarefas Celery (use `usar_contexto`).
"""

from contextlib import contextmanager
from contextvars import ContextVar

_empresa = ContextVar("empresa_atual", default=None)
_usuario = ContextVar("usuario_atual", default=None)


def empresa_atual():
    emp = _empresa.get()
    if emp is None:
        from .models import Empresa

        emp = Empresa.objects.order_by("criado_em").first()
    return emp


def usuario_atual():
    return _usuario.get()


def definir(empresa=None, usuario=None):
    return _empresa.set(empresa), _usuario.set(usuario)


def limpar(tokens):
    te, tu = tokens
    _empresa.reset(te)
    _usuario.reset(tu)


@contextmanager
def usar_contexto(empresa=None, usuario=None):
    tokens = definir(empresa, usuario)
    try:
        yield
    finally:
        limpar(tokens)
