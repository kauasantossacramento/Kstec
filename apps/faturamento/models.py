"""Faturamento recorrente: agenda por contrato, ciclos mensais e ajustes da previsão de recebimento."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import DINHEIRO, ModeloBase


class AgendaFaturamento(ModeloBase):
    """Regra de emissão mensal de NFS-e de um contrato. Cada competência gera um único ciclo."""

    class Modo(models.TextChoices):
        RASCUNHO = "RASCUNHO", "Preparar rascunho para revisão"
        CONFIRMAR = "CONFIRMAR", "Transmitir após minha confirmação"
        AUTOMATICO = "AUTOMATICO", "Transmitir automaticamente"

    class Referencia(models.TextChoices):
        MES_ANTERIOR = "MES_ANTERIOR", "Mês anterior à emissão (serviço já prestado)"
        MES_CORRENTE = "MES_CORRENTE", "Mesmo mês da emissão"

    class Vencimento(models.TextChoices):
        PRAZO = "PRAZO", "Prazo em dias após a emissão"
        DIA_FIXO = "DIA_FIXO", "Dia fixo do mês"

    contrato = models.OneToOneField("contratos.Contrato", on_delete=models.PROTECT, related_name="agenda_faturamento")
    item_catalogo = models.ForeignKey("catalogo.ItemCatalogo", on_delete=models.PROTECT, verbose_name="serviço")
    perfil = models.ForeignKey("fiscal.PerfilFiscal", null=True, blank=True, on_delete=models.PROTECT,
                               verbose_name="perfil fiscal", help_text="Vazio usa o perfil padrão da configuração fiscal.")
    empenho = models.ForeignKey("contratos.Empenho", null=True, blank=True, on_delete=models.SET_NULL,
                                help_text="Preenche {empenho} na discriminação.")
    valor = models.DecimalField("valor mensal", **DINHEIRO, validators=[MinValueValidator(Decimal("0.01"))])
    discriminacao = models.TextField("modelo da discriminação", max_length=2000, blank=True,
                                     help_text="Placeholders: {competencia}, {mes_nome}, {ano}, {parcela}, {parcela2}, {total_parcelas}, {valor}, {contrato}, {empenho}, {objeto}.")
    referencia = models.CharField("competência faturada", max_length=15, choices=Referencia.choices,
                                  default=Referencia.MES_ANTERIOR)
    dia_emissao = models.PositiveSmallIntegerField("dia da emissão", default=1,
                                                   validators=[MinValueValidator(1), MaxValueValidator(31)])
    hora_emissao = models.TimeField("horário da emissão", default="08:00")
    dia_util = models.BooleanField("adiar fins de semana para segunda-feira", default=True)
    tipo_vencimento = models.CharField("vencimento", max_length=10, choices=Vencimento.choices, default=Vencimento.PRAZO)
    prazo_dias = models.PositiveSmallIntegerField("prazo (dias)", default=30, validators=[MaxValueValidator(365)])
    dia_vencimento = models.PositiveSmallIntegerField("dia do vencimento", null=True, blank=True,
                                                      validators=[MinValueValidator(1), MaxValueValidator(31)])
    modo = models.CharField("como emitir", max_length=12, choices=Modo.choices, default=Modo.CONFIRMAR)
    inicio = models.DateField("primeira competência")
    fim = models.DateField("última competência", null=True, blank=True,
                           help_text="Vazio acompanha o fim da vigência do contrato, inclusive aditivos.")
    ativa_desde = models.DateField(default=timezone.localdate, editable=False,
                                   help_text="Emissões anteriores a esta data não são criadas automaticamente.")
    enviar_whatsapp = models.BooleanField("enviar nota ao cliente por WhatsApp", default=False)
    gerar_cobranca = models.BooleanField("gerar cobrança Asaas (link e PIX)", default=False)
    observacoes = models.TextField("observações", blank=True)

    class Meta:
        verbose_name = "agenda de faturamento"
        verbose_name_plural = "agendas de faturamento"
        ordering = ["dia_emissao", "contrato__numero"]

    def __str__(self):
        return f"Faturamento · {self.contrato.numero}"

    @property
    def fim_efetivo(self):
        return self.fim or self.contrato.vigencia_fim_atual

    @property
    def transmite(self):
        return self.modo != self.Modo.RASCUNHO


class CicloFaturamento(ModeloBase):
    """Uma emissão programada (competência) de uma agenda. Garante no máximo uma nota por competência."""

    class Status(models.TextChoices):
        PROGRAMADO = "PROGRAMADO", "Programado"
        BLOQUEADO = "BLOQUEADO", "Bloqueado por pendência"
        RASCUNHO = "RASCUNHO", "Rascunho para revisão"
        AGUARDANDO = "AGUARDANDO", "Aguardando confirmação"
        TRANSMITIDO = "TRANSMITIDO", "Transmitido · aguardando resultado"
        AUTORIZADO = "AUTORIZADO", "Autorizado"
        FALHA = "FALHA", "Falha"
        PULADO = "PULADO", "Pulado"

    FINAIS = (Status.AUTORIZADO, Status.PULADO)
    EDITAVEIS = (Status.PROGRAMADO, Status.BLOQUEADO)

    agenda = models.ForeignKey(AgendaFaturamento, on_delete=models.PROTECT, related_name="ciclos")
    competencia = models.DateField("competência")
    data_emissao = models.DateField("emissão prevista")
    data_vencimento = models.DateField("vencimento previsto")
    valor = models.DecimalField(**DINHEIRO, validators=[MinValueValidator(Decimal("0.01"))])
    discriminacao = models.TextField("discriminação deste mês", max_length=2000, blank=True,
                                     help_text="Vazio usa o modelo da agenda.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROGRAMADO, editable=False)
    nota = models.OneToOneField("fiscal.NotaFiscal", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="ciclo_faturamento", editable=False)
    mensagem = models.CharField(max_length=500, blank=True, editable=False)
    personalizado = models.BooleanField(default=False, editable=False,
                                        help_text="Valor, datas ou texto alterados só neste mês.")
    execucoes = models.PositiveIntegerField(default=0, editable=False)
    ultima_execucao = models.DateTimeField(null=True, blank=True, editable=False)
    eventos = models.JSONField(default=list, blank=True, editable=False)
    confirmado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+", editable=False)
    confirmado_em = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "ciclo de faturamento"
        verbose_name_plural = "ciclos de faturamento"
        ordering = ["data_emissao", "agenda__contrato__numero"]
        constraints = [models.UniqueConstraint(fields=["agenda", "competencia"], name="ciclo_competencia_unica")]

    def __str__(self):
        return f"{self.agenda.contrato.numero} · {self.competencia:%m/%Y}"

    def registrar(self, tipo, texto, usuario=None):
        self.eventos = [*self.eventos, {"em": timezone.now().isoformat(timespec="seconds"), "tipo": tipo,
                                        "texto": texto[:500], "usuario": str(usuario) if usuario else ""}][-50:]

    @property
    def emissao(self):
        return self.data_emissao

    @property
    def vencimento(self):
        return self.data_vencimento

    @property
    def atrasado(self):
        return self.status in self.EDITAVEIS and self.data_emissao < timezone.localdate()


class AjustePrevisao(ModeloBase):
    """Altera, só no mês indicado, a previsão de recebimento de um contrato (data, valor ou exclusão)."""

    contrato = models.ForeignKey("contratos.Contrato", on_delete=models.CASCADE, related_name="ajustes_previsao")
    mes = models.DateField("mês do recebimento", help_text="Sempre dia 1.")
    data_prevista = models.DateField("nova data prevista", null=True, blank=True)
    valor = models.DecimalField("novo valor previsto", **DINHEIRO, null=True, blank=True,
                                validators=[MinValueValidator(0)])
    excluir = models.BooleanField("não considerar recebimento neste mês", default=False)
    motivo = models.CharField(max_length=300)

    class Meta:
        verbose_name = "ajuste de previsão"
        verbose_name_plural = "ajustes de previsão"
        ordering = ["-mes"]
        constraints = [models.UniqueConstraint(fields=["contrato", "mes"], name="ajuste_previsao_mes_unico")]

    def __str__(self):
        return f"{self.contrato.numero} · {self.mes:%m/%Y}"

    def save(self, *args, **kwargs):
        self.mes = self.mes.replace(day=1)
        super().save(*args, **kwargs)
