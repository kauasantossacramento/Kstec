"""Catálogo de serviços/produtos e tabelas fiscais de referência (seção 5.4)."""

from decimal import Decimal

from django.db import models

from apps.core.models import ModeloBase

PRECO_UNIT = {"max_digits": 14, "decimal_places": 4}


# ---------------------------------------------------------------------------
# Tabelas de referência (globais, importadas dos anexos E&L / ABRASF)
# ---------------------------------------------------------------------------


class CodigoServicoLC116(models.Model):
    item = models.CharField(max_length=5, unique=True, help_text='Ex.: "01.07"')
    descricao = models.TextField("descrição")

    class Meta:
        verbose_name = "item da LC 116"
        verbose_name_plural = "itens da LC 116"
        ordering = ["item"]

    def __str__(self):
        return f"{self.item} — {self.descricao[:80]}"


class CodigoTributacaoNacional(models.Model):
    codigo = models.CharField("código", max_length=6, unique=True, help_text="6 dígitos, sem máscara (ex.: 010701)")
    item = models.CharField(max_length=2)
    subitem = models.CharField(max_length=2)
    desdobro = models.CharField(max_length=2, default="01")
    descricao = models.TextField("descrição")

    class Meta:
        verbose_name = "código de tributação nacional"
        verbose_name_plural = "códigos de tributação nacional"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} — {self.descricao[:80]}"

    @property
    def item_lc116(self) -> str:
        return f"{self.item}.{self.subitem}"


class CodigoNBS(models.Model):
    codigo = models.CharField("código", max_length=9, unique=True, help_text="9 dígitos, sem máscara")
    codigo_mascarado = models.CharField(max_length=14)
    descricao = models.TextField("descrição")

    class Meta:
        verbose_name = "código NBS"
        verbose_name_plural = "códigos NBS"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo_mascarado} — {self.descricao[:80]}"

    @staticmethod
    def mascarar(codigo: str) -> str:
        c = "".join(ch for ch in codigo if ch.isdigit()).ljust(9, "0")
        return f"{c[0]}.{c[1:5]}.{c[5:7]}.{c[7:9]}"


class CorrelacaoNBS(models.Model):
    """Anexo VIII: Item LC 116 → NBS → IndOp → cClassTrib (IBS/CBS)."""

    item_lc116 = models.CharField(max_length=5, db_index=True)
    nbs = models.CharField(max_length=9, db_index=True)
    descricao_nbs = models.TextField(blank=True)
    ps_onerosa = models.CharField(max_length=10, blank=True)
    adq_exterior = models.CharField(max_length=10, blank=True)
    ind_op = models.CharField(max_length=10, blank=True)
    local_incidencia_ibs = models.CharField(max_length=200, blank=True)
    c_class_trib = models.CharField(max_length=10, blank=True)
    nome_c_class_trib = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "correlação NBS (IBS/CBS)"
        verbose_name_plural = "correlações NBS (IBS/CBS)"
        ordering = ["item_lc116", "nbs"]

    def __str__(self):
        return f"{self.item_lc116} → {self.nbs}"


# ---------------------------------------------------------------------------
# Catálogo da empresa
# ---------------------------------------------------------------------------


class CategoriaCatalogo(ModeloBase):
    class Tipo(models.TextChoices):
        SERVICO_TI = "SERVICO_TI", "Serviço de TI"
        SERVICO_GRAFICO = "SERVICO_GRAFICO", "Serviço gráfico"
        PRODUTO_GRAFICO = "PRODUTO_GRAFICO", "Produto gráfico"
        AUDIOVISUAL = "AUDIOVISUAL", "Audiovisual"
        SOCIAL_MEDIA = "SOCIAL_MEDIA", "Social media"
        OUTRO = "OUTRO", "Outro"

    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    icone = models.CharField("ícone", max_length=30, default="package")

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class ItemCatalogo(ModeloBase):
    class Natureza(models.TextChoices):
        SERVICO = "SERVICO", "Serviço"
        PRODUTO = "PRODUTO", "Produto (mercadoria)"

    class Unidade(models.TextChoices):
        UN = "UN", "Unidade"
        HORA = "HORA", "Hora"
        MES = "MES", "Mês"
        MILHEIRO = "MILHEIRO", "Milheiro"
        M2 = "M2", "m²"
        PACOTE = "PACOTE", "Pacote"
        DIARIA = "DIARIA", "Diária"

    codigo_interno = models.CharField("código interno (SKU)", max_length=30)
    nome = models.CharField(max_length=150)
    descricao = models.TextField("descrição", blank=True)
    categoria = models.ForeignKey(CategoriaCatalogo, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="itens")
    natureza = models.CharField(max_length=10, choices=Natureza.choices, default=Natureza.SERVICO)
    unidade = models.CharField(max_length=10, choices=Unidade.choices, default=Unidade.UN)
    preco_base = models.DecimalField("preço base", **PRECO_UNIT)
    custo_base = models.DecimalField("custo base", **PRECO_UNIT, null=True, blank=True)
    margem_alvo_pct = models.DecimalField("margem alvo (%)", max_digits=6, decimal_places=2, null=True, blank=True)
    item_lc116 = models.ForeignKey(CodigoServicoLC116, null=True, blank=True, on_delete=models.PROTECT,
                                   verbose_name="item LC 116")
    codigo_tributacao_nacional = models.ForeignKey(CodigoTributacaoNacional, null=True, blank=True,
                                                   on_delete=models.PROTECT, verbose_name="código de tributação nacional")
    codigo_tributacao_municipal = models.CharField("código de tributação municipal", max_length=20, blank=True)
    nbs = models.ForeignKey(CodigoNBS, null=True, blank=True, on_delete=models.PROTECT, verbose_name="NBS")
    cnae = models.CharField("CNAE", max_length=10, blank=True)
    aliquota_iss_padrao = models.DecimalField("alíquota de ISS padrão (%)", max_digits=5, decimal_places=2,
                                              null=True, blank=True)
    ncm = models.CharField("NCM", max_length=10, blank=True, help_text="Somente produtos.")
    prazo_entrega_dias = models.PositiveSmallIntegerField("prazo de entrega (dias)", null=True, blank=True)
    permite_venda_avulsa = models.BooleanField(default=True)
    imagem = models.ImageField(upload_to="catalogo/", null=True, blank=True)

    class Meta:
        verbose_name = "item do catálogo"
        verbose_name_plural = "catálogo"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=["empresa", "codigo_interno"], name="sku_unico")]

    def __str__(self):
        return f"{self.codigo_interno} — {self.nome}"

    @property
    def pendencias_fiscais(self) -> list[str]:
        """Para emitir NFS-e, serviço exige LC 116, cTribNac e NBS. Produto exige NF-e estadual (seção 11.3)."""
        if self.natureza == self.Natureza.PRODUTO:
            return ["Item é mercadoria (ICMS): requer NF-e estadual, não NFS-e."]
        faltas = []
        if not self.item_lc116_id:
            faltas.append("Item da LC 116 não informado.")
        if not self.codigo_tributacao_nacional_id:
            faltas.append("Código de tributação nacional (cTribNac) não informado.")
        if not self.nbs_id:
            faltas.append("NBS não informado (obrigatório desde 01/2026).")
        return faltas

    @property
    def apto_nfse(self) -> bool:
        return not self.pendencias_fiscais

    @property
    def margem_atual_pct(self) -> Decimal | None:
        if not self.custo_base or not self.preco_base:
            return None
        return ((self.preco_base - self.custo_base) / self.preco_base * 100).quantize(Decimal("0.1"))


class VariacaoGrafica(ModeloBase):
    class Atributo(models.TextChoices):
        FORMATO = "FORMATO", "Formato"
        PAPEL = "PAPEL", "Papel"
        GRAMATURA = "GRAMATURA", "Gramatura"
        CORES = "CORES", "Cores"
        ACABAMENTO = "ACABAMENTO", "Acabamento"
        LAMINACAO = "LAMINACAO", "Laminação"
        CORTE = "CORTE", "Corte"

    class TipoAcrescimo(models.TextChoices):
        FIXO = "FIXO", "Valor fixo (rateado na quantidade)"
        PERCENTUAL = "PERCENTUAL", "Percentual sobre o unitário"
        POR_UNIDADE = "POR_UNIDADE", "Valor por unidade"

    item = models.ForeignKey(ItemCatalogo, on_delete=models.CASCADE, related_name="variacoes")
    atributo = models.CharField(max_length=12, choices=Atributo.choices)
    opcao = models.CharField("opção", max_length=80, help_text='Ex.: "A4", "Couché 150g", "4x4"')
    acrescimo_tipo = models.CharField("tipo de acréscimo", max_length=12, choices=TipoAcrescimo.choices,
                                      default=TipoAcrescimo.POR_UNIDADE)
    acrescimo_valor = models.DecimalField("acréscimo", **PRECO_UNIT, default=0)

    class Meta:
        verbose_name = "variação gráfica"
        verbose_name_plural = "variações gráficas"
        ordering = ["atributo", "opcao"]

    def __str__(self):
        return f"{self.get_atributo_display()}: {self.opcao}"


class FaixaPreco(ModeloBase):
    item = models.ForeignKey(ItemCatalogo, on_delete=models.CASCADE, related_name="faixas")
    quantidade_min = models.PositiveIntegerField("quantidade mínima")
    quantidade_max = models.PositiveIntegerField("quantidade máxima", null=True, blank=True)
    preco_unitario = models.DecimalField("preço unitário", **PRECO_UNIT)

    class Meta:
        verbose_name = "faixa de preço"
        verbose_name_plural = "faixas de preço"
        ordering = ["item", "quantidade_min"]

    def __str__(self):
        return f"≥ {self.quantidade_min}: {self.preco_unitario}"


