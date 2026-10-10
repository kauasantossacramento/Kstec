"""Contratos, aditivos, itens, empenhos e competências mensais (seção 5.3)."""

from datetime import date
from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import DINHEIRO, ModeloBase

ZERO = Decimal("0")


def primeiro_dia(d: date) -> date:
    return d.replace(day=1)


def somar_meses(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


class Contrato(ModeloBase):
    class Modalidade(models.TextChoices):
        DISPENSA = "DISPENSA", "Dispensa"
        PREGAO = "PREGAO", "Pregão"
        INEXIGIBILIDADE = "INEXIGIBILIDADE", "Inexigibilidade"
        CONCORRENCIA = "CONCORRENCIA", "Concorrência"
        PRIVADO = "PRIVADO", "Contrato privado"

    class Faturamento(models.TextChoices):
        MENSAL = "MENSAL", "Mensal"
        POR_ENTREGA = "POR_ENTREGA", "Por entrega"
        UNICO = "UNICO", "Único"

    class Status(models.TextChoices):
        RASCUNHO = "RASCUNHO", "Rascunho"
        VIGENTE = "VIGENTE", "Vigente"
        SUSPENSO = "SUSPENSO", "Suspenso"
        ENCERRADO = "ENCERRADO", "Encerrado"
        RESCINDIDO = "RESCINDIDO", "Rescindido"

    numero = models.CharField("número", max_length=40)
    objeto = models.TextField()
    cliente = models.ForeignKey("cadastros.Pessoa", on_delete=models.PROTECT, related_name="contratos")
    modalidade = models.CharField(max_length=20, choices=Modalidade.choices, default=Modalidade.DISPENSA)
    processo_administrativo = models.CharField(max_length=60, blank=True)
    fundamento_legal = models.CharField(max_length=200, blank=True, help_text='Ex.: "Lei 14.133/2021, art. 75, II"')
    data_assinatura = models.DateField()
    vigencia_inicio = models.DateField("início da vigência")
    vigencia_fim = models.DateField("fim da vigência")
    valor_global = models.DecimalField(**DINHEIRO)
    valor_mensal = models.DecimalField(**DINHEIRO, null=True, blank=True)
    forma_faturamento = models.CharField(max_length=12, choices=Faturamento.choices, default=Faturamento.MENSAL)
    dia_faturamento = models.PositiveSmallIntegerField(null=True, blank=True)
    prazo_pagamento_dias = models.PositiveSmallIntegerField("prazo de pagamento (dias)", default=30)
    indice_reajuste = models.CharField("índice de reajuste", max_length=20, blank=True)
    data_base_reajuste = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VIGENTE)
    gestor_contrato = models.ForeignKey("cadastros.Contato", null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name="contratos_gestor")
    fiscal_contrato = models.ForeignKey("cadastros.Contato", null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name="contratos_fiscal")
    discriminacao_padrao = models.TextField(
        "discriminação padrão", blank=True,
        help_text="Placeholders: {competencia}, {contrato}, {empenho}, {objeto}.",
    )
    exige_relatorio_atividades = models.BooleanField("exige relatório de atividades", default=True)
    exige_relatorio_sla = models.BooleanField("exige relatório de SLA", default=False)
    certidoes_exigidas = models.ManyToManyField("certidoes.TipoCertidao", blank=True, related_name="contratos")
    cor = models.CharField(max_length=7, default="#1E5BFF", help_text="Cor usada nos gráficos.")
    motivo_situacao = models.CharField("motivo da situação", max_length=300, blank=True, editable=False,
                                       help_text="Registrado ao inativar ou reativar o contrato.")
    responsaveis = models.ManyToManyField("core.Usuario", blank=True, related_name="contratos_alocados",
                                          help_text="Técnicos alocados (veem o contrato no papel Operação).")

    class Meta:
        verbose_name = "contrato"
        verbose_name_plural = "contratos"
        ordering = ["-vigencia_inicio"]
        constraints = [models.UniqueConstraint(fields=["empresa", "numero", "cliente"], name="contrato_numero_unico")]

    def __str__(self):
        return f"{self.numero} — {self.cliente}"

    # ---- indicadores (seção 5.3) ----
    @property
    def total_aditivos_valor(self) -> Decimal:
        return self.aditivos.aggregate(t=Sum("valor_acrescimo"))["t"] or ZERO

    @property
    def valor_atualizado(self) -> Decimal:
        return self.valor_global + self.total_aditivos_valor

    @property
    def total_faturado(self) -> Decimal:
        notas = getattr(self, "notas", None)
        if notas is None:
            return ZERO
        return notas.filter(status="AUTORIZADA").aggregate(t=Sum("valor_servicos"))["t"] or ZERO

    @property
    def saldo(self) -> Decimal:
        return self.valor_atualizado - self.total_faturado

    @property
    def percentual_executado(self) -> Decimal:
        if not self.valor_atualizado:
            return ZERO
        return (self.total_faturado / self.valor_atualizado * 100).quantize(Decimal("0.1"))

    @property
    def percentual_saldo(self) -> Decimal:
        return Decimal("100") - self.percentual_executado

    @property
    def vigencia_fim_atual(self) -> date:
        ultimo = self.aditivos.filter(nova_vigencia_fim__isnull=False).order_by("-data").first()
        return ultimo.nova_vigencia_fim if ultimo else self.vigencia_fim

    @property
    def dias_para_fim(self) -> int:
        return (self.vigencia_fim_atual - timezone.localdate()).days

    def render_discriminacao(self, competencia: date | None = None, empenho: str = "") -> str:
        modelo = self.discriminacao_padrao or "{objeto} — Competência {competencia}. Contrato nº {contrato}."
        return modelo.format(
            competencia=f"{competencia:%m/%Y}" if competencia else "",
            contrato=self.numero, empenho=empenho or "", objeto=self.objeto,
        )


class Aditivo(ModeloBase):
    class Tipo(models.TextChoices):
        PRAZO = "PRAZO", "Prazo"
        VALOR = "VALOR", "Valor"
        PRAZO_VALOR = "PRAZO_VALOR", "Prazo e valor"
        REAJUSTE = "REAJUSTE", "Reajuste"
        OBJETO = "OBJETO", "Objeto"

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="aditivos")
    numero = models.CharField("número", max_length=30)
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    data = models.DateField()
    nova_vigencia_fim = models.DateField("novo fim de vigência", null=True, blank=True)
    valor_acrescimo = models.DecimalField("valor de acréscimo", **DINHEIRO, null=True, blank=True,
                                          help_text="Use valor negativo para supressão.")
    percentual = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    justificativa = models.TextField(blank=True)

    class Meta:
        verbose_name = "aditivo"
        verbose_name_plural = "aditivos"
        ordering = ["data"]

    def __str__(self):
        return f"{self.numero}º aditivo ({self.get_tipo_display()})"


class ItemContrato(ModeloBase):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="itens")
    descricao = models.CharField("descrição", max_length=300)
    unidade = models.CharField(max_length=20, default="MES")
    quantidade = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    valor_unitario = models.DecimalField("valor unitário", **DINHEIRO)
    valor_total = models.DecimalField(**DINHEIRO, editable=False, default=0)

    class Meta:
        verbose_name = "item do contrato"
        verbose_name_plural = "itens do contrato"

    def __str__(self):
        return self.descricao

    def save(self, *args, **kwargs):
        self.valor_total = (self.quantidade * self.valor_unitario).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class Empenho(ModeloBase):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="empenhos")
    numero = models.CharField("número", max_length=40)
    data = models.DateField()
    valor = models.DecimalField(**DINHEIRO)
    dotacao_orcamentaria = models.CharField("dotação orçamentária", max_length=200, blank=True)
    fonte_recurso = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "empenho"
        verbose_name_plural = "empenhos"
        ordering = ["-data"]

    def __str__(self):
        return f"Empenho {self.numero}"

    @property
    def saldo(self) -> Decimal:
        notas = getattr(self, "notas", None)
        usado = notas.filter(status="AUTORIZADA").aggregate(t=Sum("valor_servicos"))["t"] if notas is not None else None
        return self.valor - (usado or ZERO)


class Competencia(ModeloBase):
    """Controle mensal do contrato (o que falta para faturar e receber cada mês)."""

    class Status(models.TextChoices):
        ABERTA = "ABERTA", "Aberta"
        EM_FATURAMENTO = "EM_FATURAMENTO", "Em faturamento"
        FATURADA = "FATURADA", "Faturada"
        PAGA = "PAGA", "Paga"

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="competencias")
    ano_mes = models.DateField("competência", help_text="Sempre dia 1 do mês.")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ABERTA)
    pacote_medicao = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="+")

    class Meta:
        verbose_name = "competência"
        verbose_name_plural = "competências"
        ordering = ["contrato", "ano_mes"]
        constraints = [models.UniqueConstraint(fields=["contrato", "ano_mes"], name="competencia_unica")]

    def __str__(self):
        return f"{self.ano_mes:%m/%Y} — {self.contrato.numero}"

    def save(self, *args, **kwargs):
        self.ano_mes = primeiro_dia(self.ano_mes)
        super().save(*args, **kwargs)


class DocumentoContrato(ModeloBase):
    """Documento enviado (assinado ou externo) de uma competência: relatório, planilha, SLA, nota etc."""

    class Tipo(models.TextChoices):
        RELATORIO_ATIVIDADES = "RELATORIO_ATIVIDADES", "Relatório de atividades"
        PLANILHA_CUSTOS = "PLANILHA_CUSTOS", "Planilha de custos"
        RELATORIO_SLA = "RELATORIO_SLA", "Relatório de SLA"
        NOTA_FISCAL = "NOTA_FISCAL", "Nota fiscal"
        CONTRATO = "CONTRATO", "Contrato, extrato ou aditivo"
        OFICIO = "OFICIO", "Ofício, justificativa ou atesto"
        OUTRO = "OUTRO", "Outro"

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="documentos")
    tipo = models.CharField(max_length=22, choices=Tipo.choices)
    competencia = models.DateField("competência", null=True, blank=True)
    titulo = models.CharField("título", max_length=200)
    assinado = models.BooleanField(default=False)
    anexo = models.ForeignKey("core.Anexo", on_delete=models.PROTECT, related_name="+")
    observacao = models.CharField("observação", max_length=300, blank=True)

    class Meta:
        verbose_name = "documento do contrato"
        verbose_name_plural = "documentos do contrato"
        ordering = ["-competencia", "tipo", "-criado_em"]

    def __str__(self):
        return self.titulo

    def save(self, *args, **kwargs):
        if self.competencia:
            self.competencia = self.competencia.replace(day=1)
        super().save(*args, **kwargs)
