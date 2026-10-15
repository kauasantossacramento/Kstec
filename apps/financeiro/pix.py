"""PIX estático (BR Code / EMV, Manual de Padrões para Iniciação do PIX do Banco Central): "copia e cola" e QR Code."""

import base64
import io
import re
import unicodedata
from decimal import Decimal


def _campo(identificador, valor):
    return f"{identificador}{len(valor):02d}{valor}"


def _ascii(texto, limite):
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]", "", texto).upper().strip()[:limite] or "NA"


def crc16(payload):
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def copia_e_cola(chave, nome, cidade, valor=None, txid="***", descricao=""):
    """Payload do PIX estático. `txid` só aceita letras e números (até 25); "***" = sem identificador."""
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave.strip())
    if descricao:
        conta += _campo("02", _ascii(descricao, 40))
    txid = re.sub(r"[^A-Za-z0-9]", "", txid)[:25] or "***"
    payload = (_campo("00", "01") + _campo("26", conta) + _campo("52", "0000") + _campo("53", "986")
               + (_campo("54", f"{Decimal(valor):.2f}") if valor else "") + _campo("58", "BR")
               + _campo("59", _ascii(nome, 25)) + _campo("60", _ascii(cidade, 15))
               + _campo("62", _campo("05", txid)) + "6304")
    return payload + crc16(payload)


def qr_data_uri(payload):
    import qrcode

    buf = io.BytesIO()
    qrcode.make(payload, box_size=6, border=2).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
