"""Monitoramento de sistemas: verificação HTTP periódica, incidentes e disponibilidade."""

from datetime import timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, Q
from django.utils import timezone

from apps.core.models import ModeloBase, ModeloSimples


class Sistema(ModeloBase):
    class Status(models.TextChoices):
        OPERACIONAL = "OPERACIONAL", "Operacional"
        DEGRADADO = "DEGRADADO", "Lento"
        FORA = "FORA", "Fora do ar"
        MANUTENCAO = "MANUTENCAO", "Em manutenção"
        DESCONHECIDO = "DESCONHECIDO", "Aguardando verificação"

    nome = models.CharField(max_length=120)
    url = models.URLField("endereço verificado", max_length=400)
    contrato = models.ForeignKey("contratos.Contrato", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="sistemas")
    metodo = models.CharField("método", max_length=4, choices=[("GET", "GET"), ("HEAD", "HEAD")], default="GET")
    status_esperado = models.PositiveSmallIntegerField("HTTP esperado", default=200)
    palavra_chave = models.CharField("texto esperado na página", max_length=120, blank=True)
    intervalo_min = models.PositiveSmallIntegerField("verificar a cada (min)", default=5,
                                                     validators=[MinValueValidator(1), MaxValueValidator(60)])
    timeout_s = models.PositiveSmallIntegerField("tempo limite (s)", default=15,
                                                 validators=[MinValueValidator(2), MaxValueValidator(60)])
    lento_ms = models.PositiveIntegerField("considerar lento acima de (ms)", default=4000)
    falhas_para_alerta = models.PositiveSmallIntegerField("falhas seguidas para alertar", default=2,
                                                          validators=[MinValueValidator(1), MaxValueValidator(10)])
    alertar_whatsapp = models.BooleanField("alertar no WhatsApp", default=True)
    alertar_email = models.BooleanField("alertar por e-mail", default=True)
    emails_alerta = models.TextField("e-mails deste sistema", blank=True,
                                     help_text="Recebem os alertas só deste sistema (ex.: TI do cliente). Separe por vírgula.")
    incluir_gerais = models.BooleanField("enviar também aos destinatários gerais", default=True)
    meta_sla = models.DecimalField("meta de disponibilidade (%)", max_digits=5, decimal_places=2, default=99,
                                   help_text="Usada no relatório mensal de SLA.")
    em_manutencao = models.BooleanField("em manutenção (sem alertas)", default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DESCONHECIDO, editable=False)
    ultima_verificacao = models.DateTimeField(null=True, blank=True, editable=False)
    ultimo_tempo_ms = models.PositiveIntegerField(null=True, blank=True, editable=False)
    ultimo_erro = models.CharField(max_length=300, blank=True, editable=False)
    falhas_consecutivas = models.PositiveSmallIntegerField(default=0, editable=False)
    ultima_mudanca = models.DateTimeField(null=True, blank=True, editable=False)
    ssl_expira_em = models.DateTimeField("certificado SSL expira em", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "sistema monitorado"
        verbose_name_plural = "sistemas monitorados"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def uptime(self, dias=30):
        desde = timezone.now() - timedelta(days=dias)
        r = self.verificacoes.filter(em__gte=desde).aggregate(total=Count("pk"), ok=Count("pk", filter=Q(sucesso=True)))
        return round(100 * r["ok"] / r["total"], 2) if r["total"] else None

    @property
    def uptime_30d(self):
        if not hasattr(self, "_uptime30"):
            self._uptime30 = self.uptime(30)
        return self._uptime30

    def tempo_medio(self, horas=24):
        desde = timezone.now() - timedelta(hours=horas)
        v = self.verificacoes.filter(em__gte=desde, sucesso=True).aggregate(m=Avg("tempo_ms"))["m"]
        return int(v) if v else None


class Verificacao(ModeloSimples):
    sistema = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name="verificacoes")
    em = models.DateTimeField(default=timezone.now, db_index=True)
    sucesso = models.BooleanField(default=False)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    tempo_ms = models.PositiveIntegerField(null=True, blank=True)
    erro = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-em"]
        indexes = [models.Index(fields=["sistema", "em"], name="verificacao_sistema_em")]


class Incidente(ModeloBase):
    class Status(models.TextChoices):
        ABERTO = "ABERTO", "Em andamento"
        FECHADO = "FECHADO", "Resolvido"

    sistema = models.ForeignKey(Sistema, on_delete=models.CASCADE, related_name="incidentes")
    inicio = models.DateTimeField()
    fim = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ABERTO)
    causa = models.CharField(max_length=300, blank=True)
    observacao = models.TextField("observação", blank=True)

    class Meta:
        verbose_name = "incidente"
        ordering = ["-inicio"]

    def __str__(self):
        return f"{self.sistema} · {timezone.localtime(self.inicio):%d/%m %H:%M}"

    @property
    def duracao(self):
        return (self.fim or timezone.now()) - self.inicio


class ConfiguracaoAlertas(ModeloBase):
    """Destinatários gerais e texto dos alertas de queda/retorno enviados por e-mail."""

    PLACEHOLDERS = "{sistema}, {url}, {erro}, {inicio}, {duracao}, {contrato}, {cliente}, {status}"

    enviar_email = models.BooleanField("enviar alertas por e-mail", default=True)
    emails_gerais = models.TextField("destinatários gerais", blank=True,
                                     help_text="Recebem alertas de todos os sistemas. Separe por vírgula ou ponto e vírgula.")
    assunto_queda = models.CharField("assunto (queda)", max_length=200, default="🔴 {sistema} fora do ar")
    corpo_queda = models.TextField("mensagem (queda)", default=(
        "Olá,\n\nO monitoramento da KS TEC identificou que o sistema {sistema} está fora do ar desde {inicio}.\n"
        "Endereço: {url}\nMotivo: {erro}\n\nNossa equipe já foi acionada e você receberá um novo aviso quando o "
        "serviço for restabelecido.\n\nKS TEC Soluções de Tecnologia"))
    assunto_retorno = models.CharField("assunto (retorno)", max_length=200, default="🟢 {sistema} restabelecido")
    corpo_retorno = models.TextField("mensagem (retorno)", default=(
        "Olá,\n\nO sistema {sistema} voltou a operar normalmente. Período de indisponibilidade: {duracao} "
        "(início em {inicio}).\n\nKS TEC Soluções de Tecnologia"))

    class Meta:
        verbose_name = "configuração de alertas"
        constraints = [models.UniqueConstraint(fields=["empresa"], name="config_alertas_empresa_unica")]


class RelatorioSLA(ModeloBase):
    """Relatório mensal de disponibilidade dos sistemas de um contrato, gerado do monitoramento."""

    contrato = models.ForeignKey("contratos.Contrato", on_delete=models.PROTECT, related_name="relatorios_sla")
    competencia = models.DateField("competência")
    versao = models.PositiveIntegerField(default=1, editable=False)
    dados = models.JSONField(default=dict, editable=False)
    observacoes = models.TextField("observações", blank=True)
    status = models.CharField(max_length=12, choices=[("RASCUNHO", "Rascunho"), ("APROVADO", "Aprovado")],
                              default="RASCUNHO", editable=False)
    aprovado_por = models.ForeignKey("core.Usuario", null=True, blank=True, on_delete=models.PROTECT, editable=False,
                                     related_name="+")
    aprovado_em = models.DateTimeField(null=True, blank=True, editable=False)
    pdf = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.PROTECT, editable=False, related_name="+")

    class Meta:
        verbose_name = "relatório de SLA"
        verbose_name_plural = "relatórios de SLA"
        ordering = ["-competencia", "-versao"]
        constraints = [models.UniqueConstraint(fields=["contrato", "competencia", "versao"], name="relatorio_sla_versao")]

    def __str__(self):
        return f"SLA {self.contrato.numero} · {self.competencia:%m/%Y} · v{self.versao}"

    def get_status_display(self):
        return dict(self._meta.get_field("status").choices)[self.status]
