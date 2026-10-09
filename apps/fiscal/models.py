"""Base fiscal auditável para preparação local de NFS-e."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import DINHEIRO, ModeloBase, ModeloSimples

PERCENTUAL = {"max_digits": 5, "decimal_places": 2,
              "validators": [MinValueValidator(0), MaxValueValidator(100)]}


class PerfilFiscal(ModeloBase):
    nome = models.CharField(max_length=120)
    iss_retido = models.BooleanField(default=False)
    aliquota_iss = models.DecimalField("alíquota ISS (%)", **PERCENTUAL)
    reter_ir = models.BooleanField(default=False)
    aliquota_ir = models.DecimalField(**PERCENTUAL, default=0)
    reter_inss = models.BooleanField(default=False)
    aliquota_inss = models.DecimalField(**PERCENTUAL, default=0)
    reter_pis = models.BooleanField(default=False)
    aliquota_pis = models.DecimalField(**PERCENTUAL, default=0)
    reter_cofins = models.BooleanField(default=False)
    aliquota_cofins = models.DecimalField(**PERCENTUAL, default=0)
    reter_csll = models.BooleanField(default=False)
    aliquota_csll = models.DecimalField(**PERCENTUAL, default=0)
    observacao_legal = models.TextField(blank=True)

    class Meta:
        verbose_name = "perfil fiscal"
        verbose_name_plural = "perfis fiscais"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class CertificadoDigital(ModeloSimples):
    nome = models.CharField(max_length=150)
    cnpj = models.CharField(max_length=14, editable=False)
    validade_inicio = models.DateTimeField(editable=False)
    validade_fim = models.DateTimeField(editable=False)
    impressao_sha256 = models.CharField(max_length=64, editable=False)
    arquivo_criptografado = models.BinaryField(editable=False)
    senha_criptografada = models.BinaryField(editable=False)
    history = HistoricalRecords(excluded_fields=["arquivo_criptografado", "senha_criptografada"])

    def __str__(self):
        return self.nome


class ConfiguracaoFiscal(ModeloBase):
    class Canal(models.TextChoices):
        MUNICIPAL_EL = "MUNICIPAL_EL", "Municipal E&L — DPS nacional"
        NACIONAL = "NACIONAL", "Emissor público nacional"

    canal_padrao = models.CharField(max_length=20, choices=Canal.choices, default=Canal.MUNICIPAL_EL)
    ambiente = models.PositiveSmallIntegerField(choices=[(2, "Homologação"), (1, "Produção")], default=2)
    serie_dps = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(79999)])
    certificado = models.ForeignKey(CertificadoDigital, null=True, blank=True, on_delete=models.PROTECT)
    token_municipal = models.ForeignKey("core.Segredo", null=True, blank=True, on_delete=models.PROTECT, editable=False)
    aliquota_iss = models.DecimalField("ISS padrão (%)", **PERCENTUAL, null=True, blank=True)
    total_tributos_simples = models.DecimalField("Tributos totais aproximados do Simples (%)", **PERCENTUAL, null=True, blank=True)
    vigencia_inicio = models.DateField(null=True, blank=True)
    vigencia_fim = models.DateField(null=True, blank=True)
    fonte_tributacao = models.CharField(max_length=300, blank=True)
    perfil_padrao = models.ForeignKey(PerfilFiscal, null=True, blank=True, on_delete=models.PROTECT)
    conta_recebimento = models.ForeignKey("financeiro.ContaBancaria", null=True, blank=True, on_delete=models.PROTECT)
    prazo_recebimento_dias = models.PositiveIntegerField(default=30, validators=[MaxValueValidator(365)])
    emissao_nacional_habilitada = models.BooleanField(default=False, editable=False)
    ultima_verificacao = models.DateTimeField(null=True, blank=True, editable=False)
    diagnostico = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["empresa"], name="config_fiscal_empresa_unica")]

    def __str__(self):
        return f"Configuração fiscal · {self.empresa}"


class SequenciaNumeracao(ModeloBase):
    ambiente = models.PositiveSmallIntegerField()
    serie = models.PositiveIntegerField()
    ultimo_numero = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["empresa", "ambiente", "serie"], name="sequencia_dps_unica")]


class NotaFiscal(ModeloBase):
    class Status(models.TextChoices):
        RASCUNHO = "RASCUNHO", "Rascunho"
        TRANSMITINDO = "TRANSMITINDO", "Transmitindo"
        EM_PROCESSAMENTO = "EM_PROCESSAMENTO", "Em processamento"
        AUTORIZADA = "AUTORIZADA", "Autorizada"
        REJEITADA = "REJEITADA", "Rejeitada"
        ERRO_COMUNICACAO = "ERRO_COMUNICACAO", "Resultado pendente de consulta"
        CANCELADA = "CANCELADA", "Cancelada"

    tomador = models.ForeignKey("cadastros.Pessoa", on_delete=models.PROTECT)
    contrato = models.ForeignKey("contratos.Contrato", on_delete=models.PROTECT, null=True, blank=True, related_name="notas")
    item_catalogo = models.ForeignKey("catalogo.ItemCatalogo", on_delete=models.PROTECT)
    perfil = models.ForeignKey(PerfilFiscal, on_delete=models.PROTECT)
    competencia = models.DateField("competência")
    discriminacao = models.TextField("discriminação", max_length=2000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RASCUNHO, editable=False)
    valor_servicos = models.DecimalField("valor dos serviços", **DINHEIRO, validators=[MinValueValidator(0)])
    valor_deducoes = models.DecimalField("deduções", **DINHEIRO, default=0, validators=[MinValueValidator(0)])
    desconto_incondicionado = models.DecimalField(**DINHEIRO, default=0, validators=[MinValueValidator(0)])
    desconto_condicionado = models.DecimalField(**DINHEIRO, default=0, validators=[MinValueValidator(0)])
    outras_retencoes = models.DecimalField("outras retenções", **DINHEIRO, default=0, validators=[MinValueValidator(0)])
    aliquota_iss = models.DecimalField("alíquota ISS (%)", **PERCENTUAL, null=True, blank=True,
                                     help_text="No Simples, informe a alíquota da competência confirmada pelo contador.")
    base_calculo = models.DecimalField(**DINHEIRO, default=0, editable=False)
    valor_iss = models.DecimalField(**DINHEIRO, default=0, editable=False)
    iss_retido = models.BooleanField(default=False, editable=False)
    valor_iss_retido = models.DecimalField(**DINHEIRO, default=0, editable=False)
    valor_ir = models.DecimalField(**DINHEIRO, default=0, editable=False)
    valor_inss = models.DecimalField(**DINHEIRO, default=0, editable=False)
    valor_pis = models.DecimalField(**DINHEIRO, default=0, editable=False)
    valor_cofins = models.DecimalField(**DINHEIRO, default=0, editable=False)
    valor_csll = models.DecimalField(**DINHEIRO, default=0, editable=False)
    valor_liquido = models.DecimalField(**DINHEIRO, default=0, editable=False)
    tomador_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    servico_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    perfil_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    emissao_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    numero_nfse = models.CharField(max_length=30, blank=True, editable=False)
    chave_acesso = models.CharField(max_length=50, blank=True, editable=False)
    id_dps = models.CharField(max_length=45, blank=True, editable=False)
    canal = models.CharField(max_length=20, choices=ConfiguracaoFiscal.Canal.choices, blank=True, editable=False)
    ambiente = models.PositiveSmallIntegerField(null=True, blank=True, editable=False, choices=[(1, "Produção"), (2, "Homologação")])
    autorizada_em = models.DateTimeField(null=True, blank=True, editable=False)
    xml_autorizado = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")
    vencimento_recebivel = models.DateField(null=True, blank=True)
    pdf = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")

    class Meta:
        verbose_name = "NFS-e"
        verbose_name_plural = "NFS-e"
        ordering = ["-criado_em"]
        constraints = [models.UniqueConstraint(fields=["empresa", "ambiente", "chave_acesso"],
                          condition=~models.Q(chave_acesso=""), name="nfse_chave_unica")]

    def __str__(self):
        return f"{self.numero_nfse or str(self.pk)[:8]} — {self.tomador}"


class TentativaTransmissao(ModeloBase):
    nota = models.ForeignKey(NotaFiscal, on_delete=models.PROTECT, related_name="tentativas")
    canal = models.CharField(max_length=20, choices=ConfiguracaoFiscal.Canal.choices)
    ambiente = models.PositiveSmallIntegerField()
    id_dps = models.CharField(max_length=45)
    situacao = models.CharField(max_length=50, default="PREPARADA")
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    resposta = models.JSONField(default=dict, blank=True)
    consultas = models.JSONField(default=list, blank=True)
    dps_assinada = models.ForeignKey("core.Anexo", on_delete=models.PROTECT, related_name="+")
    hash_requisicao = models.CharField(max_length=64)

    class Meta:
        ordering = ["-criado_em"]
        constraints = [models.UniqueConstraint(fields=["nota", "canal"], name="tentativa_nota_canal_unica")]


class EntregaNota(ModeloBase):
    class Status(models.TextChoices):
        PREPARADA = "PREPARADA", "Preparada para revisão"
        ENVIANDO = "ENVIANDO", "Envio iniciado"
        ENVIADA = "ENVIADA", "Aceita pelo servidor de e-mail"
        SIMULADA = "SIMULADA", "Simulada no ambiente local"
        INCERTA = "INCERTA", "Resultado do envio inconclusivo"

    nota = models.ForeignKey(NotaFiscal, on_delete=models.PROTECT, related_name="entregas")
    destinatarios = models.JSONField(default=list)
    assunto = models.CharField(max_length=200)
    mensagem = models.TextField(max_length=10000)
    pacote = models.ForeignKey("core.Anexo", on_delete=models.PROTECT, related_name="+")
    manifesto = models.JSONField(default=dict)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PREPARADA, editable=False)
    enviado_em = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-criado_em"]
