"""Configuração por empresa e custódia cifrada das credenciais fiscais."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.cripto import cifrar, decifrar, decifrar_texto
from apps.core.models import Segredo

from ..certificado import CertificadoA1
from ..models import CertificadoDigital, ConfiguracaoFiscal


@transaction.atomic
def cadastrar_certificado(empresa, dados, senha, nome="Certificado A1"):
    if len(dados) > 2_000_000:
        raise ValidationError("O certificado deve ter no máximo 2 MB.")
    a1 = CertificadoA1(dados, senha, empresa.cnpj)
    cert = CertificadoDigital(empresa=empresa, nome=nome[:150], cnpj=a1.cnpj,
                             validade_inicio=a1.certificado.not_valid_before_utc,
                             validade_fim=a1.certificado.not_valid_after_utc,
                             impressao_sha256=a1.metadados()["sha256"],
                             arquivo_criptografado=cifrar(dados), senha_criptografada=cifrar(senha))
    cert.save()
    return cert


def carregar_a1(config):
    cert = config.certificado
    if not cert or cert.empresa_id != config.empresa_id or not cert.ativo:
        raise ValidationError("Cadastre um certificado ativo da empresa.")
    return CertificadoA1(decifrar(cert.arquivo_criptografado), decifrar_texto(cert.senha_criptografada), config.empresa.cnpj)


@transaction.atomic
def salvar_configuracao(config, *, token="", arquivo=None, senha=""):
    config.full_clean()
    for campo in ("certificado", "perfil_padrao", "conta_recebimento", "token_municipal"):
        obj = getattr(config, campo, None)
        if obj and obj.empresa_id != config.empresa_id:
            raise ValidationError("Configuração vinculada a outra empresa.")
    if config.vigencia_inicio and config.vigencia_fim and config.vigencia_fim < config.vigencia_inicio:
        raise ValidationError("A vigência final não pode ser anterior à inicial.")
    if config.aliquota_iss is not None and not 2 <= config.aliquota_iss <= 5:
        raise ValidationError("ISS padrão tributável deve estar entre 2% e 5%.")
    if arquivo is not None:
        if not senha:
            raise ValidationError("Informe a senha do certificado enviado.")
        config.certificado = cadastrar_certificado(config.empresa, arquivo.read(), senha, arquivo.name)
    if token.strip():
        config.token_municipal = Segredo.criar("Token municipal E&L", token.strip(), "FISCAL", config.empresa)
    config.full_clean()
    config.save()
    return config


def checklist(config, competencia=None):
    itens = []
    if config is None:
        return [("Configuração fiscal cadastrada", False)]
    data = competencia or timezone.localdate()
    itens.extend([
        ("Inscrição municipal do emitente", bool(config.empresa.inscricao_municipal)),
        ("Certificado A1 ativo e dentro da validade", bool(config.certificado and config.certificado.ativo
          and config.certificado.cnpj == config.empresa.cnpj
          and config.certificado.validade_inicio <= timezone.now() < config.certificado.validade_fim)),
        ("Percentuais informados com fonte e vigência para a competência", bool(
            config.aliquota_iss is not None and config.total_tributos_simples is not None
            and config.fonte_tributacao and config.vigencia_inicio and config.vigencia_fim
            and config.vigencia_inicio <= data <= config.vigencia_fim)),
        ("Perfil fiscal padrão", bool(config.perfil_padrao_id)),
    ])
    if config.canal_padrao == ConfiguracaoFiscal.Canal.MUNICIPAL_EL:
        itens.append(("Token municipal configurado", bool(config.token_municipal_id)))
    else:
        itens.append(("Município habilitado para emissão pública nacional", config.emissao_nacional_habilitada))
    return itens
