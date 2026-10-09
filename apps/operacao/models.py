from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import ModeloBase


class Tarefa(ModeloBase):
    class Tipo(models.TextChoices):
        DESENVOLVIMENTO = "DESENVOLVIMENTO", "Desenvolvimento"
        CORRECAO = "CORRECAO", "Correção"
        SUPORTE = "SUPORTE", "Suporte"
        MANUTENCAO = "MANUTENCAO", "Manutenção"
        IMPLANTACAO = "IMPLANTACAO", "Implantação"
        TREINAMENTO = "TREINAMENTO", "Treinamento"
        REUNIAO = "REUNIAO", "Reunião"
        CONTEUDO = "CONTEUDO", "Conteúdo"
        INFRA = "INFRA", "Infraestrutura"

    class Status(models.TextChoices):
        A_FAZER = "A_FAZER", "A fazer"
        EM_ANDAMENTO = "EM_ANDAMENTO", "Em andamento"
        EM_REVISAO = "EM_REVISAO", "Em revisão"
        CONCLUIDA = "CONCLUIDA", "Concluída"
        CANCELADA = "CANCELADA", "Cancelada"

    class Prioridade(models.TextChoices):
        BAIXA = "BAIXA", "Baixa"
        NORMAL = "NORMAL", "Normal"
        ALTA = "ALTA", "Alta"
        URGENTE = "URGENTE", "Urgente"

    contrato = models.ForeignKey("contratos.Contrato", null=True, blank=True, on_delete=models.PROTECT, related_name="tarefas")
    titulo = models.CharField("título", max_length=200)
    descricao = models.TextField("descrição", blank=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.SUPORTE)
    prioridade = models.CharField(max_length=10, choices=Prioridade.choices, default=Prioridade.NORMAL)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.A_FAZER, editable=False)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tarefas")
    solicitante = models.ForeignKey("cadastros.Contato", null=True, blank=True, on_delete=models.PROTECT)
    protocolo_cliente = models.CharField(max_length=100, blank=True)
    data_abertura = models.DateField(default=timezone.localdate)
    prazo = models.DateField(null=True, blank=True)
    concluida_em = models.DateTimeField(null=True, blank=True, editable=False)
    horas_estimadas = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True,
                                         validators=[MinValueValidator(Decimal("0.01"))])
    entrar_no_relatorio = models.BooleanField("incluir no relatório", default=True)
    resumo_para_relatorio = models.TextField("resumo do que foi entregue", blank=True)

    class Meta:
        verbose_name = "tarefa"
        verbose_name_plural = "tarefas"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.titulo


class Apontamento(ModeloBase):
    tarefa = models.ForeignKey(Tarefa, on_delete=models.PROTECT, related_name="apontamentos")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    data = models.DateField(default=timezone.localdate)
    horas = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    descricao = models.TextField("descrição")

    class Meta:
        verbose_name = "apontamento de horas"
        verbose_name_plural = "apontamentos de horas"
        ordering = ["-data", "-criado_em"]
        constraints = [models.CheckConstraint(condition=models.Q(horas__gt=0, horas__lte=24), name="apontamento_horas_validas")]

    def __str__(self):
        return f"{self.tarefa} · {self.horas} h"


class RelatorioAtividades(ModeloBase):
    contrato = models.ForeignKey("contratos.Contrato", on_delete=models.PROTECT, related_name="relatorios_atividades")
    competencia = models.DateField("competência")
    versao = models.PositiveIntegerField(default=1, editable=False)
    introducao = models.TextField("introdução", blank=True)
    conteudo = models.TextField("atividades e entregas", max_length=30000)
    consideracoes_finais = models.TextField("considerações finais", blank=True)
    tarefas_snapshot = models.JSONField(default=list, blank=True, editable=False)
    status = models.CharField(max_length=12, choices=[("RASCUNHO", "Rascunho"), ("APROVADO", "Aprovado")],
                              default="RASCUNHO", editable=False)
    aprovado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")
    aprovado_em = models.DateTimeField(null=True, blank=True, editable=False)
    pdf = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")

    class Meta:
        ordering = ["-competencia", "-versao"]
        constraints = [models.UniqueConstraint(fields=["contrato", "competencia", "versao"], name="relatorio_atividades_versao")]

    def __str__(self):
        return f"{self.contrato.numero} · {self.competencia:%m/%Y} · v{self.versao}"
