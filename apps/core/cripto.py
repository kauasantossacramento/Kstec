"""Criptografia simétrica (Fernet) para segredos guardados no banco (seção 3.3)."""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    chave = settings.FIELD_ENCRYPTION_KEY
    if not chave:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY não configurada.")
    return Fernet(chave.encode() if isinstance(chave, str) else chave)


def cifrar(dados: bytes | str) -> bytes:
    if isinstance(dados, str):
        dados = dados.encode("utf-8")
    return _fernet().encrypt(dados)


def decifrar(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(bytes(token))
    except InvalidToken as e:
        raise ImproperlyConfigured("Não foi possível decifrar: FIELD_ENCRYPTION_KEY diferente da usada na gravação.") from e


def decifrar_texto(token: bytes) -> str:
    return decifrar(token).decode("utf-8")
