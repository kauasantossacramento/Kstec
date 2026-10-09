"""Orçamentos com aprovação por link público e vendas avulsas (seções 5.7 e 11)."""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.utils import timezone

from apps.core.models import DINHEIRO, ModeloBase

D2 = Decimal("0.01")


class Orcamento(ModeloBase):
    class Status(models.TextChoices):
        RASCUNHO = "RASCUNHO", "Rascunho"
        ENVIADO = "ENVIADO", "Enviado"
        VISUALIZADO = "VISUALIZADO", "Visualizado"
        APROVADO = "APROVADO", "Aprovado"
        RECUSADO = "RECUSADO", "Recusado"
        EXPIRADO = "EXPIRADO", "Expirado"
        CONVERTIDO = "CONVERTIDO", "Convertido em venda"

    class TipoDesconto(models.TextChoices):
        VALOR = "VALOR", "Valor (R$)"
        PERCENTUAL = "PERCENTUAL", "Percentual (%)"

    numero = models.CharField("número", max_length=20, editable=False)
    cliente = models.ForeignKey("cadastros.Pessoa", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="orcamentos")
    cliente_avulso_nome = models.CharField("cliente avulso — nome", max_length=200, blank=True)
    cliente_avulso_doc = models.CharField("cliente avulso — CPF/CNPJ", max_length=18, blank=True)
    cliente_avulso_contato = models.CharField("cliente avulso — e-mail/telefone", max_length=200, blank=True)
    data = models.DateField(default=timezone.localdate)
    validade = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RASCUNHO)
    condicoes_pagamento = models.CharField("condições de pagamento", max_length=200, blank=True,
                                           default="50% na aprovação e 50% na entrega")
    prazo_entrega = models.CharField(max_length=100, blank=True)
    observacoes = models.TextField("observações", blank=True)
    desconto_tipo = models.CharField(max_length=10, choices=TipoDesconto.choices, default=TipoDesconto.VALOR)
    desconto_valor = models.DecimalField("desconto", **DINHEIRO, default=0)
    subtotal = models.DecimalField(**DINHEIRO, default=0, editable=False)
    total = models.DecimalField(**DINHEIRO, default=0, editable=False)
    token_publico = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    enviado_em = models.DateTimeField(null=True, blank=True, editable=False)
    visualizado_em = models.DateTimeField(null=True, blank=True, editable=False)
    aprovado_em = models.DateTimeField(null=True, blank=True, editable=False)
    aprovado_por_nome = models.CharField(max_length=150, blank=True, editable=False)
    ip_aprovacao = models.GenericIPAddressField(null=True, blank=True, editable=False)
    ajuste_solicitado = models.TextField(blank=True, editable=False)
    followup_em = models.DateTimeField(null=True, blank=True, editable=False)
    pdf = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                            editable=False)

    class Meta:
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        ordering = ["-data", "-numero"]

    def __str__(self):
        return f"{self.numero} — {self.nome_cliente}"

    def save(self, *args, **kwargs):
        if not self.numero:
            from apps.core.models import Contador

            ano = (self.data or timezone.localdate()).year
            n = Contador.proximo(f"ORC-{ano}", empresa=self.empresa if self.empresa_id else None)
            self.numero = f"ORC-{ano}-{n:04d}"
        super().save(*args, **kwargs)

    @property
    def nome_cliente(self) -> str:
        return str(self.cliente) if self.cliente_id else (self.cliente_avulso_nome or "Cliente avulso")

    @property
    def email_cliente(self) -> str:
        if self.cliente_id:
            return self.cliente.email
        c = self.cliente_avulso_contato
        return c if "@" in c else ""

    @property
    def valor_desconto(self) -> Decimal:
        if self.desconto_tipo == self.TipoDesconto.PERCENTUAL:
            return (self.subtotal * self.desconto_valor / 100).quantize(D2, ROUND_HALF_UP)
        return self.desconto_valor

    def recalcular(self, salvar=True):
        self.subtotal = sum((i.total for i in self.itens.all()), Decimal("0"))
        self.total = max(self.subtotal - self.valor_desconto, Decimal("0"))
        if salvar:
            self.save(update_fields=["subtotal", "total", "atualizado_em"])

    @property
    def editavel(self) -> bool:
        return self.status in (self.Status.RASCUNHO, self.Status.ENVIADO, self.Status.VISUALIZADO)

    @property
    def expirado(self) -> bool:
        return self.validade < timezone.localdate()


class ItemOrcamento(ModeloBase):
    orcamento = models.ForeignKey(Orcamento, on_delete=models.CASCADE, related_name="itens")
    item_catalogo = models.ForeignKey("catalogo.ItemCatalogo", null=True, blank=True, on_delete=models.PROTECT)
    descricao = models.CharField("descrição", max_length=500)
    variacoes = models.JSONField(default=list, blank=True)
    quantidade = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    preco_unitario = models.DecimalField("preço unitário", max_digits=14, decimal_places=4)
    desconto = models.DecimalField(**DINHEIRO, default=0)
    total = models.DecimalField(**DINHEIRO, default=0, editable=False)
    ordem = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "item do orçamento"
        verbose_name_plural = "itens do orçamento"
        ordering = ["ordem", "criado_em"]

    def __str__(self):
        return self.descricao

    def save(self, *args, **kwargs):
        self.total = (self.quantidade * self.preco_unitario - (self.desconto or 0)).quantize(D2, ROUND_HALF_UP)
        super().save(*args, **kwargs)

    @property
    def variacoes_texto(self) -> str:
        return ", ".join(v.get("rotulo", "") for v in self.variacoes or [])


class Venda(ModeloBase):
    class Status(models.TextChoices):
        ABERTA = "ABERTA", "Aberta"
        EM_PRODUCAO = "EM_PRODUCAO", "Em produção"
        ENTREGUE = "ENTREGUE", "Entregue"
        FATURADA = "FATURADA", "Faturada"
        CANCELADA = "CANCELADA", "Cancelada"

    numero = models.CharField("número", max_length=20, editable=False)
    orcamento = models.OneToOneField(Orcamento, null=True, blank=True, on_delete=models.SET_NULL, related_name="venda")
    cliente = models.ForeignKey("cadastros.Pessoa", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="vendas")
    cliente_avulso_nome = models.CharField(max_length=200, blank=True)
    data = models.DateField(default=timezone.localdate)
    total = models.DecimalField(**DINHEIRO, default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ABERTA)
    gera_nf = models.BooleanField("gera nota fiscal", default=True)
    parcelas = models.PositiveSmallIntegerField(default=1)
    primeiro_vencimento = models.DateField(null=True, blank=True)
    observacoes = models.TextField("observações", blank=True)

    class Meta:
        verbose_name = "venda"
        verbose_name_plural = "vendas"
        ordering = ["-data", "-numero"]

    def __str__(self):
        return f"{self.numero} — {self.cliente or self.cliente_avulso_nome}"

    def save(self, *args, **kwargs):
        if not self.numero:
            from apps.core.models import Contador

            ano = (self.data or timezone.localdate()).year
            n = Contador.proximo(f"VND-{ano}", empresa=self.empresa if self.empresa_id else None)
            self.numero = f"VND-{ano}-{n:04d}"
        super().save(*args, **kwargs)


class ItemVenda(ModeloBase):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name="itens")
    item_catalogo = models.ForeignKey("catalogo.ItemCatalogo", null=True, blank=True, on_delete=models.PROTECT)
    descricao = models.CharField("descrição", max_length=500)
    variacoes = models.JSONField(default=list, blank=True)
    quantidade = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=4)
    desconto = models.DecimalField(**DINHEIRO, default=0)
    total = models.DecimalField(**DINHEIRO, default=0)

    class Meta:
        verbose_name = "item da venda"
        verbose_name_plural = "itens da venda"

    def __str__(self):
        return self.descricao
