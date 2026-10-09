"""Contas, categorias, centros de custo e lançamentos com histórico auditável."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import DINHEIRO, ModeloBase


class PlanilhaCustos(ModeloBase):
    contrato = models.ForeignKey("contratos.Contrato", on_delete=models.PROTECT, related_name="planilhas_custos")
    competencia = models.DateField("competência")
    versao = models.PositiveIntegerField(default=1, editable=False)
    status = models.CharField(max_length=12, choices=[("RASCUNHO", "Rascunho"), ("APROVADO", "Aprovado")],
                              default="RASCUNHO", editable=False)
    observacoes = models.TextField("observações e fontes", blank=True)
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")
    aprovado_em = models.DateTimeField(null=True, blank=True, editable=False)
    xlsx = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")
    pdf = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")
    administracao_central = models.DecimalField("Administração central (%)", max_digits=5, decimal_places=2, default=0,
                                               validators=[MinValueValidator(0), MaxValueValidator(100)])
    seguro_garantia = models.DecimalField("Seguro/garantia (%)", max_digits=5, decimal_places=2, default=0,
                                        validators=[MinValueValidator(0), MaxValueValidator(100)])
    risco = models.DecimalField("Risco (%)", max_digits=5, decimal_places=2, default=0,
                               validators=[MinValueValidator(0), MaxValueValidator(100)])
    despesas_financeiras = models.DecimalField("Despesas financeiras (%)", max_digits=5, decimal_places=2, default=0,
                                               validators=[MinValueValidator(0), MaxValueValidator(100)])
    lucro = models.DecimalField("Lucro (%)", max_digits=5, decimal_places=2, default=0,
                                validators=[MinValueValidator(0), MaxValueValidator(100)])
    tributos = models.DecimalField("Tributos sobre faturamento (%)", max_digits=5, decimal_places=2, default=0,
                                   validators=[MinValueValidator(0), MaxValueValidator(Decimal("99.99"))])

    class Meta:
        ordering = ["-competencia", "-versao"]
        constraints = [models.UniqueConstraint(fields=["contrato", "competencia", "versao"], name="planilha_custos_versao")]

    @property
    def bdi(self):
        a, s, r, df, lucro, i = [getattr(self, f) / 100 for f in
                             ("administracao_central", "seguro_garantia", "risco", "despesas_financeiras", "lucro", "tributos")]
        return (1 + a + s + r) * (1 + df) * (1 + lucro) / (1 - i) - 1

    def __str__(self):
        return f"{self.contrato.numero} · {self.competencia:%m/%Y} · v{self.versao}"


class ItemCusto(ModeloBase):
    planilha = models.ForeignKey(PlanilhaCustos, on_delete=models.CASCADE, related_name="itens")
    grupo = models.CharField(max_length=20, choices=[("MAO_DE_OBRA", "Mão de obra"), ("INFRAESTRUTURA", "Infraestrutura"),
               ("LICENCAS", "Licenças e APIs"), ("INSUMOS", "Insumos"), ("DESLOCAMENTO", "Deslocamento"), ("INDIRETOS", "Custos indiretos")])
    descricao = models.CharField("descrição", max_length=250)
    unidade = models.CharField(max_length=20, default="un")
    quantidade = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=4, validators=[MinValueValidator(0)])
    rateio_pct = models.DecimalField("rateio (%)", max_digits=5, decimal_places=2, default=100,
                                   validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(100)])
    periodicidade = models.CharField(max_length=10, choices=[("MENSAL", "Mensal"), ("ANUAL", "Anual / 12"), ("UNICO", "Único nesta competência")], default="MENSAL")
    fonte = models.CharField(max_length=250)

    @property
    def valor_mensal(self):
        from decimal import ROUND_HALF_UP

        divisor = 12 if self.periodicidade == "ANUAL" else 1
        return (self.quantidade * self.valor_unitario * self.rateio_pct / 100 / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class ContaBancaria(ModeloBase):
    nome = models.CharField(max_length=100)
    banco_codigo = models.CharField("código do banco", max_length=10, blank=True)
    agencia = models.CharField("agência", max_length=20, blank=True)
    conta = models.CharField(max_length=30, blank=True)
    saldo_inicial = models.DecimalField(**DINHEIRO, default=0)
    data_saldo_inicial = models.DateField(default=timezone.localdate)

    class Meta:
        verbose_name = "conta bancária"
        verbose_name_plural = "contas bancárias"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class CategoriaFinanceira(ModeloBase):
    class Tipo(models.TextChoices):
        RECEITA = "RECEITA", "Receita"
        DESPESA = "DESPESA", "Despesa"

    class Grupo(models.TextChoices):
        RECEITA_BRUTA = "RECEITA_BRUTA", "Receita bruta"
        DEDUCOES = "DEDUCOES", "Deduções"
        CUSTO_SERVICO = "CUSTO_SERVICO", "Custos dos serviços"
        DESPESA_OPERACIONAL = "DESPESA_OPERACIONAL", "Despesas operacionais"
        DESPESA_FINANCEIRA = "DESPESA_FINANCEIRA", "Despesas financeiras"
        IMPOSTOS = "IMPOSTOS", "Impostos"
        INVESTIMENTO = "INVESTIMENTO", "Investimentos"
        NAO_OPERACIONAL = "NAO_OPERACIONAL", "Não operacional"

    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    grupo_dre = models.CharField("grupo no demonstrativo", max_length=25, choices=Grupo.choices)

    class Meta:
        verbose_name = "categoria financeira"
        verbose_name_plural = "categorias financeiras"
        ordering = ["tipo", "nome"]
        constraints = [models.UniqueConstraint(fields=["empresa", "nome"], name="categoria_financeira_unica")]

    def __str__(self):
        return self.nome


class CentroCusto(ModeloBase):
    nome = models.CharField(max_length=150)
    contrato = models.OneToOneField("contratos.Contrato", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="centro_custo")

    class Meta:
        verbose_name = "centro de custo"
        verbose_name_plural = "centros de custo"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=["empresa", "nome"], name="centro_custo_unico")]

    def __str__(self):
        return self.nome


class Lancamento(ModeloBase):
    class Tipo(models.TextChoices):
        RECEITA = "RECEITA", "Receita"
        DESPESA = "DESPESA", "Despesa"

    class Status(models.TextChoices):
        PREVISTO = "PREVISTO", "Previsto"
        PENDENTE = "PENDENTE", "Pendente"
        PAGO = "PAGO", "Pago"
        ATRASADO = "ATRASADO", "Atrasado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Forma(models.TextChoices):
        PIX = "PIX", "PIX"
        BOLETO = "BOLETO", "Boleto"
        TED = "TED", "Transferência"
        CARTAO = "CARTAO", "Cartão"
        DINHEIRO = "DINHEIRO", "Dinheiro"
        OB = "OB", "Ordem bancária"

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    descricao = models.CharField("descrição", max_length=300)
    pessoa = models.ForeignKey("cadastros.Pessoa", null=True, blank=True, on_delete=models.PROTECT)
    categoria = models.ForeignKey(CategoriaFinanceira, on_delete=models.PROTECT)
    centro_custo = models.ForeignKey(CentroCusto, on_delete=models.PROTECT, related_name="lancamentos")
    conta_bancaria = models.ForeignKey(ContaBancaria, null=True, blank=True, on_delete=models.PROTECT, related_name="lancamentos")
    valor = models.DecimalField(**DINHEIRO, validators=[MinValueValidator(Decimal("0.01"))])
    data_competencia = models.DateField("data de competência")
    data_vencimento = models.DateField("vencimento")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDENTE, editable=False)
    data_pagamento = models.DateField("data de pagamento", null=True, blank=True, editable=False)
    valor_pago = models.DecimalField(**DINHEIRO, null=True, blank=True, editable=False)
    juros = models.DecimalField(**DINHEIRO, default=0, editable=False)
    multa = models.DecimalField(**DINHEIRO, default=0, editable=False)
    desconto = models.DecimalField(**DINHEIRO, default=0, editable=False)
    forma_pagamento = models.CharField(max_length=12, choices=Forma.choices, blank=True, editable=False)
    ordem_bancaria = models.CharField("ordem bancária", max_length=100, blank=True, editable=False)
    data_liquidacao = models.DateField("liquidação", null=True, blank=True, editable=False)
    nota_fiscal = models.OneToOneField("fiscal.NotaFiscal", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="recebivel", editable=False)
    conciliado = models.BooleanField(default=False, editable=False)
    motivo_cancelamento = models.CharField(max_length=300, blank=True, editable=False)
    recorrencia = models.ForeignKey("Recorrencia", null=True, blank=True, on_delete=models.PROTECT, editable=False)

    class Meta:
        verbose_name = "lançamento"
        verbose_name_plural = "lançamentos"
        ordering = ["data_vencimento", "-criado_em"]
        constraints = [models.CheckConstraint(condition=models.Q(valor__gt=0), name="lancamento_valor_positivo"),
            models.UniqueConstraint(fields=["empresa", "recorrencia", "data_competencia"], name="recorrencia_competencia_unica")]

    def __str__(self):
        return self.descricao

    @property
    def vencido(self):
        return self.status in (self.Status.PENDENTE, self.Status.PREVISTO, self.Status.ATRASADO) and self.data_vencimento < timezone.localdate()


class Recorrencia(ModeloBase):
    class Frequencia(models.TextChoices):
        MENSAL = "MENSAL", "Mensal"
        ANUAL = "ANUAL", "Anual"

    descricao = models.CharField("descrição", max_length=300)
    tipo = models.CharField(max_length=10, choices=Lancamento.Tipo.choices)
    categoria = models.ForeignKey(CategoriaFinanceira, on_delete=models.PROTECT)
    centro_custo = models.ForeignKey(CentroCusto, on_delete=models.PROTECT)
    conta_bancaria = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT)
    pessoa = models.ForeignKey("cadastros.Pessoa", null=True, blank=True, on_delete=models.PROTECT)
    valor = models.DecimalField(**DINHEIRO, validators=[MinValueValidator(Decimal("0.01"))])
    frequencia = models.CharField("frequência", max_length=10, choices=Frequencia.choices, default=Frequencia.MENSAL)
    dia = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(31)])
    inicio = models.DateField("início")
    fim = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "recorrência"
        verbose_name_plural = "recorrências"
        ordering = ["descricao"]

    def __str__(self):
        return self.descricao


class TransacaoExtrato(ModeloBase):
    conta_bancaria = models.ForeignKey(ContaBancaria, on_delete=models.PROTECT, related_name="transacoes")
    identificador_externo = models.CharField(max_length=200)
    data = models.DateField()
    valor = models.DecimalField(**DINHEIRO)
    descricao = models.CharField(max_length=300)
    hash_arquivo = models.CharField(max_length=64, editable=False)
    lancamento = models.OneToOneField(Lancamento, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="transacao_extrato", editable=False)
    conciliada_em = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-data", "identificador_externo"]
        constraints = [models.UniqueConstraint(fields=["conta_bancaria", "identificador_externo"],
                        name="transacao_bancaria_unica"),
                       models.CheckConstraint(condition=~models.Q(valor=0), name="transacao_valor_nao_zero")]

    def __str__(self):
        return self.descricao
