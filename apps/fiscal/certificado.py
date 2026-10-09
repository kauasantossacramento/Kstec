"""A1 em memória; chave temporária sempre cifrada e removida após carregar o TLS."""
import re
import secrets
import ssl
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ObjectIdentifier
from django.core.exceptions import ValidationError


class CertificadoA1:
    def __init__(self, arquivo, senha, cnpj_esperado=None):
        try:
            self.chave, self.certificado, self.cadeia = load_key_and_certificates(
                arquivo if isinstance(arquivo, bytes) else Path(arquivo).read_bytes(),
                senha.encode() if isinstance(senha, str) else senha)
        except (ValueError, OSError) as erro:
            raise ValidationError("Não foi possível abrir o A1: confira arquivo e senha.") from erro
        if self.chave is None or self.certificado is None:
            raise ValidationError("O arquivo deve conter certificado e chave privada.")
        self.cnpj = self._cnpj()
        if not self.cnpj or (cnpj_esperado and self.cnpj != cnpj_esperado):
            raise ValidationError("O CNPJ do certificado não corresponde ao prestador.")
        agora = datetime.now(UTC)
        if not self.certificado.not_valid_before_utc <= agora < self.certificado.not_valid_after_utc:
            raise ValidationError("Certificado fora do período de validade.")
        try:
            usos = self.certificado.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        except x509.ExtensionNotFound:
            raise ValidationError("Certificado sem extensão de autenticação cliente.")
        if ExtendedKeyUsageOID.CLIENT_AUTH not in usos:
            raise ValidationError("Certificado sem uso de autenticação cliente.")
        formato = serialization.PublicFormat.SubjectPublicKeyInfo
        if self.chave.public_key().public_bytes(serialization.Encoding.DER, formato) != self.certificado.public_key().public_bytes(serialization.Encoding.DER, formato):
            raise ValidationError("Chave privada incompatível com o certificado.")

    def _cnpj(self):
        try:
            san = self.certificado.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            for nome in san:
                if isinstance(nome, x509.OtherName) and nome.type_id == ObjectIdentifier("2.16.76.1.3.3"):
                    if len(nome.value) == 16 and nome.value[:2] in (b"\x13\x0e", b"\x0c\x0e", b"\x16\x0e"):
                        valor = nome.value[2:].decode("ascii")
                        if re.fullmatch(r"[0-9]{14}", valor):
                            return valor
        except (x509.ExtensionNotFound, UnicodeError):
            pass
        return ""

    def metadados(self):
        return {"cnpj": self.cnpj, "titular": self.certificado.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
                "validade_inicio": self.certificado.not_valid_before_utc.isoformat(),
                "validade_fim": self.certificado.not_valid_after_utc.isoformat(),
                "sha256": self.certificado.fingerprint(hashes.SHA256()).hex(), "cadeia_no_pfx": len(self.cadeia)}

    def contexto_tls(self):
        contexto = ssl.create_default_context()
        senha_efemera = secrets.token_bytes(32)
        with TemporaryDirectory(prefix="kscentral-a1-") as pasta:
            certificado = Path(pasta) / "certificado.pem"
            chave = Path(pasta) / "chave-cifrada.pem"
            certificado.write_bytes(b"".join(c.public_bytes(serialization.Encoding.PEM) for c in [self.certificado, *self.cadeia]))
            chave.write_bytes(self.chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.BestAvailableEncryption(senha_efemera)))
            contexto.load_cert_chain(str(certificado), str(chave), password=senha_efemera)
        return contexto
