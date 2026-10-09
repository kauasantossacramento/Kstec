"""Trava distribuída sobre o cache (Redis em produção, memória no perfil local).

`cache.add` é atômico no Redis (SET NX) e garante que apenas um worker/beat execute
a mesma rotina ao mesmo tempo. O token impede que um processo libere a trava de outro
após o TTL expirar.
"""

import uuid
from contextlib import contextmanager

from django.core.cache import cache


class TravaOcupada(Exception):
    pass


@contextmanager
def trava(chave: str, ttl: int = 600):
    nome = f"trava:{chave}"
    token = uuid.uuid4().hex
    if not cache.add(nome, token, ttl):
        raise TravaOcupada(chave)
    try:
        yield
    finally:
        if cache.get(nome) == token:
            cache.delete(nome)


def executar_com_trava(chave: str, funcao, *args, ttl: int = 600, **kwargs):
    """Executa `funcao` se a trava estiver livre; caso contrário retorna None sem erro."""
    try:
        with trava(chave, ttl):
            return funcao(*args, **kwargs)
    except TravaOcupada:
        return None
