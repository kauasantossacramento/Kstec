"""WhatsApp: configuração anti-bloqueio, sessão, contatos com consentimento, fila, lotes e confirmações."""

from datetime import time

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import ModeloBase, ModeloSimples
from apps.core.validadores import formatar_telefone, normalizar_telefone, validar_telefone


class ConfiguracaoWhatsApp(ModeloBase):
    class Transporte(models.TextChoices):
        SIMULADO = "SIMULADO", "Simulado (registra sem enviar)"
        NEONIZE = "NEONIZE", "WhatsApp Web (neonize)"

    class SemResposta(models.TextChoices):
        AGUARDAR = "AGUARDAR", "Continuar aguardando"
        CANCELAR = "CANCELAR", "Cancelar o envio"
        ENVIAR = "ENVIAR", "Enviar mesmo assim"

    ativo = models.BooleanField("WhatsApp ativo", default=False)
    transporte = models.CharField(max_length=10, choices=Transporte.choices, default=Transporte.SIMULADO)
    numeros_admin = models.CharField("meus números (administradores)", max_length=200, blank=True,
                                     help_text="Recebem alertas, resumos e podem enviar comandos. Separe por vírgula.")
    # janela e ritmo — principais defesas contra bloqueio
    horario_inicio = models.TimeField("enviar a partir de", default=time(8, 0))
    horario_fim = models.TimeField("enviar até", default=time(19, 0))
    dias_uteis = models.BooleanField("somente dias úteis para clientes", default=True)
    limite_hora = models.PositiveSmallIntegerField("máximo por hora", default=15,
                                                   validators=[MinValueValidator(1), MaxValueValidator(60)])
    limite_dia = models.PositiveSmallIntegerField("máximo por dia", default=60,
                                                  validators=[MinValueValidator(1), MaxValueValidator(300)])
    intervalo_min = models.PositiveSmallIntegerField("intervalo mínimo (s)", default=25,
                                                     validators=[MinValueValidator(5), MaxValueValidator(600)])
    intervalo_max = models.PositiveSmallIntegerField("intervalo máximo (s)", default=75,
                                                     validators=[MinValueValidator(5), MaxValueValidator(1800)])
    simular_digitacao = models.BooleanField("mostrar “digitando…” antes de enviar", default=True)
    novos_por_dia = models.PositiveSmallIntegerField("primeiras mensagens a contatos novos por dia", default=10,
                                                     validators=[MinValueValidator(1), MaxValueValidator(50)])
    # confirmação
    confirmar_envios = models.BooleanField("pedir minha confirmação antes de enviar a clientes", default=True)
    prazo_confirmacao_h = models.PositiveSmallIntegerField("prazo para confirmar (horas)", default=24,
                                                           validators=[MinValueValidator(1), MaxValueValidator(168)])
    sem_resposta = models.CharField("sem resposta no prazo", max_length=10, choices=SemResposta.choices,
                                    default=SemResposta.CANCELAR)
    # recursos
    alertas_monitoramento = models.BooleanField("avisar quedas e retornos dos sistemas monitorados", default=True)
    avisos_faturamento = models.BooleanField("avisar eventos do faturamento recorrente", default=True)
    resumo_diario = models.BooleanField("enviar resumo diário", default=False)
    hora_resumo = models.TimeField("horário do resumo", default=time(8, 0))
    comandos = models.BooleanField("responder comandos dos meus números", default=True)
    lembretes_cobranca = models.BooleanField("enviar lembretes de cobrança aos clientes", default=True)
    hora_lembretes = models.TimeField("horário dos lembretes", default=time(9, 30))
    # assistente (Gemini)
    assistente_ia = models.BooleanField("responder perguntas livres com IA (Gemini)", default=False)
    gemini_chave = models.ForeignKey("core.Segredo", null=True, blank=True, on_delete=models.PROTECT, editable=False,
                                     related_name="+")
    modelo_ia = models.CharField("modelo Gemini", max_length=60, default="gemini-flash-latest")
    reiniciar_sessao = models.BooleanField(default=False, editable=False,
                                           help_text="Pedido da tela para o worker recriar a conexão (novo QR).")

    class Meta:
        verbose_name = "configuração do WhatsApp"
        constraints = [models.UniqueConstraint(fields=["empresa"], name="config_whatsapp_empresa_unica")]

    def __str__(self):
        return "Configuração do WhatsApp"

    @property
    def admins(self) -> list[str]:
        return [n for n in (normalizar_telefone(x) for x in self.numeros_admin.split(",")) if n]


class EstadoSessao(ModeloSimples):
    """Estado do processo `whatsapp_worker` (único consumidor da fila)."""

    class Estado(models.TextChoices):
        DESLIGADO = "DESLIGADO", "Worker desligado"
        AGUARDANDO_QR = "AGUARDANDO_QR", "Aguardando leitura do QR Code"
        CONECTADO = "CONECTADO", "Conectado"
        DESCONECTADO = "DESCONECTADO", "Desconectado"
        ERRO = "ERRO", "Erro"

    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.DESLIGADO)
    qr = models.TextField(blank=True)
    qr_em = models.DateTimeField(null=True, blank=True)
    conta = models.CharField(max_length=60, blank=True)
    batimento = models.DateTimeField(null=True, blank=True)
    pausado_ate = models.DateTimeField(null=True, blank=True)
    motivo_pausa = models.CharField(max_length=200, blank=True)
    falhas_seguidas = models.PositiveSmallIntegerField(default=0)
    detalhe = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["empresa"], name="estado_whatsapp_empresa_unico")]

    @property
    def vivo(self):
        return bool(self.batimento and (timezone.now() - self.batimento).total_seconds() < 90)


class ContatoWhatsApp(ModeloBase):
    pessoa = models.ForeignKey("cadastros.Pessoa", null=True, blank=True, on_delete=models.CASCADE,
                               related_name="contatos_whatsapp")
    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=20, validators=[validar_telefone])
    consentimento = models.BooleanField("autorizou receber mensagens", default=False)
    consentimento_em = models.DateTimeField(null=True, blank=True, editable=False)
    origem_consentimento = models.CharField("como autorizou", max_length=200, blank=True,
                                            help_text="Ex.: cláusula do contrato, e-mail de 10/10/2026, pedido verbal registrado.")
    recebe_notas = models.BooleanField("notas fiscais", default=True)
    recebe_cobrancas = models.BooleanField("cobranças e lembretes", default=True)
    verificado = models.BooleanField("número com WhatsApp", null=True, blank=True, editable=False)
    jid = models.CharField(max_length=80, blank=True, editable=False)
    descadastrado_em = models.DateTimeField(null=True, blank=True, editable=False,
                                            help_text="Pediu para não receber (SAIR).")
    primeira_mensagem_em = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "contato de WhatsApp"
        verbose_name_plural = "contatos de WhatsApp"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=["empresa", "pessoa", "telefone"], name="contato_whatsapp_unico")]

    def __str__(self):
        return f"{self.nome} · {self.telefone_formatado}"

    def save(self, *args, **kwargs):
        self.telefone = normalizar_telefone(self.telefone) or self.telefone
        if self.consentimento and not self.consentimento_em:
            self.consentimento_em = timezone.now()
        if not self.consentimento:
            self.consentimento_em = None
        super().save(*args, **kwargs)

    @property
    def telefone_formatado(self):
        return formatar_telefone(self.telefone)

    @property
    def apto(self):
        return self.ativo and self.consentimento and not self.descadastrado_em and self.verificado is not False


class LoteEnvio(ModeloBase):
    """Conjunto de mensagens a clientes que pode exigir confirmação do administrador."""

    class Status(models.TextChoices):
        AGUARDANDO = "AGUARDANDO", "Aguardando confirmação"
        LIBERADO = "LIBERADO", "Liberado para envio"
        CONCLUIDO = "CONCLUIDO", "Enviado"
        CANCELADO = "CANCELADO", "Cancelado"
        EXPIRADO = "EXPIRADO", "Expirado sem resposta"

    titulo = models.CharField(max_length=200)
    origem = models.CharField(max_length=20, default="MANUAL")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.LIBERADO, editable=False)
    resumo = models.TextField(blank=True)
    codigo = models.CharField(max_length=6, blank=True, db_index=True)
    expira_em = models.DateTimeField(null=True, blank=True)
    decidido_em = models.DateTimeField(null=True, blank=True)
    decidido_por = models.CharField(max_length=120, blank=True)
    nota = models.ForeignKey("fiscal.NotaFiscal", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "lote de envio"
        verbose_name_plural = "lotes de envio"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.titulo


class MensagemWhatsApp(ModeloSimples):
    class Status(models.TextChoices):
        RETIDA = "RETIDA", "Retida para confirmação"
        PENDENTE = "PENDENTE", "Na fila"
        ENVIANDO = "ENVIANDO", "Enviando"
        ENVIADA = "ENVIADA", "Enviada"
        SIMULADA = "SIMULADA", "Simulada"
        FALHA = "FALHA", "Falha"
        CANCELADA = "CANCELADA", "Cancelada"
        RECEBIDA = "RECEBIDA", "Recebida"

    class Tipo(models.TextChoices):
        TEXTO = "TEXTO", "Texto"
        DOCUMENTO = "DOCUMENTO", "Documento"

    class Prioridade(models.IntegerChoices):
        ALTA = 1, "Alta (administrador)"
        NORMAL = 5, "Normal"

    direcao = models.CharField(max_length=7, choices=[("SAIDA", "Enviada"), ("ENTRADA", "Recebida")], default="SAIDA")
    telefone = models.CharField(max_length=20)
    contato = models.ForeignKey(ContatoWhatsApp, null=True, blank=True, on_delete=models.SET_NULL, related_name="mensagens")
    lote = models.ForeignKey(LoteEnvio, null=True, blank=True, on_delete=models.CASCADE, related_name="mensagens")
    para_admin = models.BooleanField(default=False)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.TEXTO)
    texto = models.TextField(blank=True)
    anexo = models.ForeignKey("core.Anexo", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    nome_arquivo = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE)
    prioridade = models.PositiveSmallIntegerField(choices=Prioridade.choices, default=Prioridade.NORMAL)
    ordem = models.PositiveSmallIntegerField(default=0)
    agendada_para = models.DateTimeField(default=timezone.now)
    enviada_em = models.DateTimeField(null=True, blank=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    erro = models.CharField(max_length=300, blank=True)
    chave = models.CharField(max_length=160, blank=True, db_index=True)
    wa_id = models.CharField(max_length=80, blank=True, db_index=True)

    class Meta:
        verbose_name = "mensagem de WhatsApp"
        verbose_name_plural = "mensagens de WhatsApp"
        ordering = ["-criado_em"]
        indexes = [models.Index(fields=["status", "prioridade", "agendada_para"], name="msg_fila_idx")]

    def __str__(self):
        return f"{self.get_direcao_display()} · {formatar_telefone(self.telefone)}"

    @property
    def telefone_formatado(self):
        return formatar_telefone(self.telefone)


class Confirmacao(ModeloSimples):
    """Pedido de confirmação respondível no WhatsApp (SIM/NAO + código) ou na tela."""

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        RECUSADA = "RECUSADA", "Recusada"
        EXPIRADA = "EXPIRADA", "Expirada"

    codigo = models.CharField(max_length=6, db_index=True)
    acao = models.CharField(max_length=60)
    objeto_id = models.CharField(max_length=40)
    descricao = models.CharField(max_length=300)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDENTE)
    expira_em = models.DateTimeField()
    respondida_em = models.DateTimeField(null=True, blank=True)
    respondida_por = models.CharField(max_length=120, blank=True)
    resultado = models.CharField(max_length=300, blank=True)
    dados = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-criado_em"]
