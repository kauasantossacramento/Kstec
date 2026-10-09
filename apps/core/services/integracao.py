"""Registro de chamadas externas em LogIntegracao, com mascaramento de segredos (seção 3.3)."""

import json
import re
import time
from contextlib import contextmanager

from django.contrib.contenttypes.models import ContentType

from ..models import LogIntegracao

_PADROES_SEGREDO = [
    (re.compile(r'("?(senha|password|token|api[_-]?key|chave|authorization|aceites_autenticacao)"?\s*[:=]\s*")[^"]*(")', re.I),
     r"\1***\3"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1***"),
    (re.compile(r"(<ds:X509Certificate>|<X509Certificate>)[^<]+(</)"), r"\1***\2"),
]
LIMITE = 200_000


def mascarar(texto) -> str:
    if texto is None:
        return ""
    if isinstance(texto, bytes):
        texto = texto.decode("utf-8", errors="replace")
    if not isinstance(texto, str):
        try:
            texto = json.dumps(texto, ensure_ascii=False, default=str)
        except TypeError:
            texto = str(texto)
    for padrao, subst in _PADROES_SEGREDO:
        texto = padrao.sub(subst, texto)
    return texto[:LIMITE]


def registrar_log(servico, operacao, *, objeto=None, request=None, response=None, status_http=None,
                  duracao_ms=None, sucesso=False, chave_idempotencia="", empresa=None) -> LogIntegracao:
    log = LogIntegracao(
        servico=servico,
        operacao=operacao,
        chave_idempotencia=chave_idempotencia or "",
        request=mascarar(request),
        response=mascarar(response),
        status_http=status_http,
        duracao_ms=duracao_ms,
        sucesso=sucesso,
    )
    if empresa is not None:
        log.empresa = empresa
    elif objeto is not None and getattr(objeto, "empresa_id", None):
        log.empresa_id = objeto.empresa_id
    if objeto is not None and getattr(objeto, "pk", None):
        log.content_type = ContentType.objects.get_for_model(objeto)
        log.object_id = str(objeto.pk)
    log.save()
    return log


@contextmanager
def cronometro():
    """Uso: with cronometro() as t: ...; t() -> ms decorridos."""
    inicio = time.perf_counter()
    yield lambda: int((time.perf_counter() - inicio) * 1000)
