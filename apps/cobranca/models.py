"""Cobrança via Asaas (link de pagamento, boleto e PIX) e preferências de cobrança por cliente."""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import DINHEIRO, ModeloBase


class Forma(models.TextChoices):
    PIX = "PIX", "PIX"
    BOLETO = "BOLETO", "Boleto (com PIX)"
    UNDEFINED = "UNDEFINED", "Cliente escolhe (PIX, boleto ou cartão)"


def validar_dias(valor):
    if valor and not re.fullmatch(r"\s*\d{1,2}(\s*,\s*\d{1,2})*\s*", valor):
        raise ValidationError("Use números separados por vírgula, por exemplo 3,0.")


def dias(valor) -> list[int]:
    return sorted({int(x) for x in re.findall(r"\d{1,2}", valor or "")})


class ConfiguracaoAsaas(ModeloBase):
    class Ambiente(models.TextChoices):
        SANDBOX = "SANDBOX", "Sandbox (testes)"
        PRODUCAO = "PRODUCAO", "Produção"

    ambiente = models.CharField(max_length=10, choices=Ambiente.choices, default=Ambiente.SANDBOX)
    api_key = models.ForeignKey("core.Segredo", null=True, blank=True, on_delete=models.PROTECT, editable=False,
                                related_name="+")
    webhook_token = models.ForeignKey("core.Segredo", null=True, blank=True, on_delete=models.PROTECT,
                                      editable=False, related_name="+")
    forma_padrao = models.CharField("forma de pagamento padrão", max_length=10, choices=Forma.choices,
                                    default=Forma.UNDEFINED)
    multa_pct = models.DecimalField("multa por atraso (%)", max_digits=5, decimal_places=2, default=0,
                                    validators=[MinValueValidator(0), MaxValueValidator(Decimal("10"))])
    juros_mes_pct = models.DecimalField("juros ao mês (%)", max_digits=5, decimal_places=2, default=0,
                                        validators=[MinValueValidator(0), MaxValueValidator(Decimal("10"))])
    baixa_automatica = models.BooleanField("registrar baixa automaticamente ao confirmar pagamento", default=True)
    conta_recebimento = models.ForeignKey("financeiro.ContaBancaria", null=True, blank=True, on_delete=models.PROTECT,
                                          verbose_name="conta da baixa", help_text="Conta Asaas no financeiro.")
    verificado_em = models.DateTimeField(null=True, blank=True, editable=False)
    conta_nome = models.CharField(max_length=200, blank=True, editable=False)

    class Meta:
        verbose_name = "configuração Asaas"
        constraints = [models.UniqueConstraint(fields=["empresa"], name="config_asaas_empresa_unica")]

    def __str__(self):
        return f"Asaas · {self.get_ambiente_display()}"

    @property
    def pronta(self):
        return bool(self.ativo and self.api_key_id)


class PerfilCobranca(ModeloBase):
    """Como cobrar e notificar um cliente. WhatsApp exige também contato com consentimento."""

    class Confirmacao(models.TextChoices):
        HERDAR = "HERDAR", "Seguir a configuração do WhatsApp"
        SEMPRE = "SEMPRE", "Sempre pedir minha confirmação"
        NUNCA = "NUNCA", "Enviar sem confirmação"

    pessoa = models.OneToOneField("cadastros.Pessoa", on_delete=models.CASCADE, related_name="perfil_cobranca")
    whatsapp_ativo = models.BooleanField("comunicar por WhatsApp", default=False,
                                         help_text="Chave geral: sem ela, nada é enviado a este cliente.")
    enviar_nota = models.BooleanField("enviar NFS-e (PDF e XML) quando emitida", default=True)
    enviar_lembretes = models.BooleanField("enviar lembretes de vencimento", default=True)
    dias_antes = models.CharField("lembrar dias antes do vencimento", max_length=40, default="3,0", blank=True,
                                  validators=[validar_dias], help_text="0 = no dia do vencimento.")
    dias_depois = models.CharField("lembrar dias após o vencimento", max_length=40, default="1,5", blank=True,
                                   validators=[validar_dias])
    link_pagamento = models.BooleanField("incluir link de pagamento / PIX (Asaas)", default=True)
    forma = models.CharField("forma de pagamento", max_length=10, choices=Forma.choices, blank=True,
                             help_text="Vazio usa a forma padrão do Asaas.")
    confirmacao = models.CharField("confirmação antes de enviar", max_length=10, choices=Confirmacao.choices,
                                   default=Confirmacao.HERDAR)
    asaas_cliente_id = models.CharField(max_length=40, blank=True, editable=False)

    class Meta:
        verbose_name = "perfil de cobrança"
        verbose_name_plural = "perfis de cobrança"

    def __str__(self):
        return f"Cobrança · {self.pessoa}"


class CobrancaAsaas(ModeloBase):
    ABERTOS = ("PENDING", "OVERDUE", "AWAITING_RISK_ANALYSIS")
    PAGOS = ("RECEIVED", "CONFIRMED", "RECEIVED_IN_CASH")
    ROTULOS = {"PENDING": "Aguardando pagamento", "OVERDUE": "Vencida", "RECEIVED": "Recebida",
               "CONFIRMED": "Confirmada", "RECEIVED_IN_CASH": "Recebida em dinheiro", "REFUNDED": "Estornada",
               "DELETED": "Removida", "AWAITING_RISK_ANALYSIS": "Em análise"}

    lancamento = models.ForeignKey("financeiro.Lancamento", on_delete=models.PROTECT, related_name="cobrancas_asaas")
    nota = models.ForeignKey("fiscal.NotaFiscal", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    ambiente = models.CharField(max_length=10, choices=ConfiguracaoAsaas.Ambiente.choices)
    asaas_id = models.CharField(max_length=40)
    status = models.CharField(max_length=30, default="PENDING")
    forma = models.CharField(max_length=10, choices=Forma.choices)
    valor = models.DecimalField(**DINHEIRO)
    vencimento = models.DateField()
    link_fatura = models.URLField(max_length=400, blank=True)
    link_boleto = models.URLField(max_length=400, blank=True)
    pix_copia_cola = models.TextField(blank=True)
    pix_qr = models.TextField(blank=True, help_text="PNG em base64 retornado pelo Asaas.")
    pix_expira = models.DateTimeField(null=True, blank=True)
    pago_em = models.DateField(null=True, blank=True)
    valor_pago = models.DecimalField(**DINHEIRO, null=True, blank=True)
    eventos = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "cobrança Asaas"
        verbose_name_plural = "cobranças Asaas"
        ordering = ["-criado_em"]
        constraints = [models.UniqueConstraint(fields=["ambiente", "asaas_id"], name="cobranca_asaas_unica")]

    def __str__(self):
        return f"Cobrança {self.asaas_id} · {self.lancamento}"

    def get_status_display(self):
        return self.ROTULOS.get(self.status, self.status.replace("_", " ").capitalize())

    @property
    def aberta(self):
        return self.status in self.ABERTOS
