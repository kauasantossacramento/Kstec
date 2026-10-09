"""Certidões e habilitação (seções 5.12 e 10)."""

from django.db import models
from django.utils import timezone

from apps.core.models import ModeloBase

DIAS_VENCENDO = 15


class TipoCertidao(ModeloBase):
    class Esfera(models.TextChoices):
        FEDERAL = "FEDERAL", "Federal"
        ESTADUAL = "ESTADUAL", "Estadual"
        MUNICIPAL = "MUNICIPAL", "Municipal"
        TRABALHISTA = "TRABALHISTA", "Trabalhista"
        JUDICIAL = "JUDICIAL", "Judicial"
        OUTRA = "OUTRA", "Outra"

    nome = models.CharField(max_length=150)
    orgao_emissor = models.CharField("órgão emissor", max_length=150)
    esfera = models.CharField(max_length=12, choices=Esfera.choices)
    url_emissao = models.URLField("URL de emissão", blank=True)
    validade_padrao_dias = models.PositiveSmallIntegerField("validade padrão (dias)", default=180)
    obrigatoria_habilitacao = models.BooleanField("obrigatória para habilitação", default=True)
    instrucoes = models.TextField("instruções", blank=True)

    class Meta:
        verbose_name = "tipo de certidão"
        verbose_name_plural = "tipos de certidão"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    @property
    def vigente(self):
        return (self.certidoes.filter(ativo=True, data_validade__gte=timezone.localdate())
                .order_by("-data_validade").first())

    @property
    def ultima(self):
        return self.certidoes.filter(ativo=True).order_by("-data_validade").first()


class Certidao(ModeloBase):
    class Situacao(models.TextChoices):
        NEGATIVA = "NEGATIVA", "Negativa"
        POSITIVA_COM_EFEITO_NEGATIVA = "POSITIVA_COM_EFEITO_NEGATIVA", "Positiva com efeito de negativa"
        POSITIVA = "POSITIVA", "Positiva"

    tipo = models.ForeignKey(TipoCertidao, on_delete=models.PROTECT, related_name="certidoes")
    numero = models.CharField("número / código de controle", max_length=100, blank=True)
    data_emissao = models.DateField("data de emissão")
    data_validade = models.DateField("data de validade")
    arquivo = models.FileField(upload_to="certidoes/%Y/", blank=True)
    situacao = models.CharField("situação", max_length=30, choices=Situacao.choices, default=Situacao.NEGATIVA)
    codigo_autenticidade = models.CharField("código de autenticidade", max_length=100, blank=True)
    url_validacao = models.URLField("URL de validação", blank=True)
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "certidão"
        verbose_name_plural = "certidões"
        ordering = ["-data_validade"]

    def __str__(self):
        return f"{self.tipo} — válida até {self.data_validade:%d/%m/%Y}"

    @property
    def dias_restantes(self) -> int:
        return (self.data_validade - timezone.localdate()).days

    @property
    def status(self) -> str:
        """VALIDA, VENCENDO (≤ 15 dias) ou VENCIDA."""
        d = self.dias_restantes
        if d < 0:
            return "VENCIDA"
        return "VENCENDO" if d <= DIAS_VENCENDO else "VALIDA"

    def get_status_display(self):
        return {"VALIDA": "Válida", "VENCENDO": "Vencendo", "VENCIDA": "Vencida"}[self.status]


class KitHabilitacao(ModeloBase):
    nome = models.CharField(max_length=200, help_text='Ex.: "Dispensa 012/2026 — Prefeitura X"')
    certidoes = models.ManyToManyField(Certidao, blank=True, related_name="kits")
    documentos_extra = models.ManyToManyField("core.Anexo", blank=True, related_name="+",
                                              help_text="Contrato social, cartão CNPJ, atestados…")
    zip = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                            editable=False)
    gerado_em = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "kit de habilitação"
        verbose_name_plural = "kits de habilitação"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.nome
