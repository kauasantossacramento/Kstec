"""Modelos do núcleo: empresa, usuários, auditoria, anexos, parâmetros, notificações, segredos e logs."""

import hashlib

import uuid6
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from . import contexto
from .cripto import cifrar, decifrar_texto
from .validadores import formatar_doc, so_digitos, validar_cnpj

DINHEIRO = {"max_digits": 14, "decimal_places": 2}


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class ModeloSimples(models.Model):
    """Campos comuns (UUID v7, empresa, carimbos, autor) sem histórico — para logs e segredos."""

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="+", editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.empresa_id:
            emp = contexto.empresa_atual()
            if emp is not None:
                self.empresa = emp
        if self._state.adding and not self.criado_por_id:
            usr = contexto.usuario_atual()
            if usr is not None and getattr(usr, "pk", None):
                self.criado_por = usr
        super().save(*args, **kwargs)


class ModeloBase(ModeloSimples):
    """Base de todos os modelos de negócio (seção 5): ModeloSimples + histórico (simple_history)."""

    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Empresa e endereço
# ---------------------------------------------------------------------------


class Endereco(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    cep = models.CharField(max_length=9)
    tipo_logradouro = models.CharField(max_length=30, blank=True, default="Rua")
    logradouro = models.CharField(max_length=200)
    numero = models.CharField(max_length=20, blank=True, default="S/N")
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100)
    municipio_ibge = models.CharField("código IBGE", max_length=7)
    municipio_nome = models.CharField("município", max_length=100)
    uf = models.CharField(max_length=2)
    pais_bacen = models.CharField(max_length=4, default="1058")
    history = HistoricalRecords()

    class Meta:
        verbose_name = "endereço"
        verbose_name_plural = "endereços"

    def save(self, *args, **kwargs):
        self.cep = so_digitos(self.cep)
        self.uf = (self.uf or "").upper()
        super().save(*args, **kwargs)

    def __str__(self):
        num = f", {self.numero}" if self.numero else ""
        return f"{self.logradouro}{num} — {self.bairro}, {self.municipio_nome}/{self.uf}"


class Empresa(models.Model):
    class Regime(models.TextChoices):
        SIMPLES = "SIMPLES", "Simples Nacional"
        LUCRO_PRESUMIDO = "LUCRO_PRESUMIDO", "Lucro Presumido"
        LUCRO_REAL = "LUCRO_REAL", "Lucro Real"
        MEI = "MEI", "MEI"

    REGIME_ESPECIAL = [
        (0, "0 — Nenhum"),
        (1, "1 — Microempresa municipal"),
        (2, "2 — Estimativa"),
        (3, "3 — Sociedade de profissionais"),
        (4, "4 — Cooperativa"),
        (5, "5 — MEI"),
        (6, "6 — ME/EPP"),
        (7, "7 — Profissional autônomo"),
        (8, "8 — Notário ou registrador"),
        (9, "9 — Outros"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    razao_social = models.CharField("razão social", max_length=200)
    nome_fantasia = models.CharField(max_length=200, blank=True)
    cnpj = models.CharField(max_length=14, unique=True, validators=[validar_cnpj])
    inscricao_municipal = models.CharField("inscrição municipal", max_length=30, blank=True)
    inscricao_estadual = models.CharField("inscrição estadual", max_length=30, blank=True)
    regime_tributario = models.CharField("regime tributário", max_length=20, choices=Regime.choices, default=Regime.SIMPLES)
    optante_simples = models.BooleanField("optante do Simples", default=True)
    regime_especial_tributacao = models.PositiveSmallIntegerField("regime especial de tributação", choices=REGIME_ESPECIAL, default=0)
    natureza_juridica = models.CharField("natureza jurídica", max_length=100, blank=True)
    cnae_principal = models.CharField(max_length=10, blank=True)
    cnaes_secundarios = models.JSONField(default=list, blank=True)
    endereco = models.ForeignKey(Endereco, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    site = models.URLField(blank=True)
    logo = models.ImageField(upload_to="publico/logos/", null=True, blank=True)
    cor_primaria = models.CharField(max_length=7, default="#0016E1")
    municipio_ibge = models.CharField("código IBGE do município", max_length=7, default="2932903")
    responsavel_tecnico = models.CharField("responsável técnico", max_length=150, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"

    def __str__(self):
        return self.nome_fantasia or self.razao_social

    def save(self, *args, **kwargs):
        self.cnpj = so_digitos(self.cnpj)
        super().save(*args, **kwargs)

    @property
    def cnpj_formatado(self):
        return formatar_doc(self.cnpj)

    @property
    def cod_op_simples_nacional(self) -> int:
        """Domínio opSimpNac da DPS: 1 não optante · 2 MEI · 3 ME/EPP (conferir manual vigente)."""
        if self.regime_tributario == self.Regime.MEI:
            return 2
        return 3 if self.optante_simples else 1

    @classmethod
    def atual(cls):
        return contexto.empresa_atual()


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _criar(self, email, password, **extra):
        if not email:
            raise ValueError("E-mail é obrigatório.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, username=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._criar(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._criar(email, password, **extra)


class Usuario(AbstractUser):
    """Usuário do sistema; o login é feito por e-mail. Papéis via Group."""

    PAPEIS = ["Administrador", "Financeiro", "Fiscal", "Operação", "Leitura"]

    class Tema(models.TextChoices):
        CLARO = "claro", "Claro"
        ESCURO = "escuro", "Escuro"

    email = models.EmailField("e-mail", unique=True)
    nome = models.CharField(max_length=150, blank=True)
    empresa = models.ForeignKey(Empresa, null=True, blank=True, on_delete=models.PROTECT, related_name="usuarios")
    cpf = models.CharField(max_length=11, blank=True)
    cargo = models.CharField(max_length=100, blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to="publico/avatares/", null=True, blank=True)
    tema = models.CharField(max_length=10, choices=Tema.choices, default=Tema.CLARO)
    mfa_ativo = models.BooleanField(default=False)
    history = HistoricalRecords(excluded_fields=["password", "last_login"])

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UsuarioManager()

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self):
        return self.nome or self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or "").lower()
        self.username = self.email
        super().save(*args, **kwargs)

    @property
    def papeis(self) -> list[str]:
        if not hasattr(self, "_papeis_cache"):
            self._papeis_cache = list(self.groups.values_list("name", flat=True))
        return self._papeis_cache

    def tem_papel(self, *papeis) -> bool:
        if self.is_superuser:
            return True
        return bool(set(papeis) & set(self.papeis))

    @property
    def somente_leitura(self) -> bool:
        return not self.is_superuser and set(self.papeis) <= {"Leitura"}

    @property
    def exige_mfa(self) -> bool:
        return self.is_superuser or self.tem_papel(*settings.MFA_PAPEIS_OBRIGATORIOS)

    @property
    def iniciais(self) -> str:
        partes = (self.nome or self.email).replace("@", " ").split()
        return "".join(p[0] for p in partes[:2]).upper()


# ---------------------------------------------------------------------------
# Anexos, parâmetros, notificações, segredos, logs
# ---------------------------------------------------------------------------


def _caminho_anexo(instance, filename):
    agora = timezone.localtime()
    return f"anexos/{agora:%Y/%m}/{instance.id}_{filename}"


class Anexo(ModeloBase):
    class Tipo(models.TextChoices):
        XML = "XML", "XML"
        PDF = "PDF", "PDF"
        IMAGEM = "IMAGEM", "Imagem"
        PLANILHA = "PLANILHA", "Planilha"
        ZIP = "ZIP", "ZIP"
        DOCX = "DOCX", "DOCX"
        OUTRO = "OUTRO", "Outro"

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=40, blank=True, db_index=True)
    objeto = GenericForeignKey("content_type", "object_id")
    arquivo = models.FileField(upload_to=_caminho_anexo, max_length=300)
    nome = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.OUTRO)
    tamanho = models.PositiveBigIntegerField(default=0)
    hash_sha256 = models.CharField(max_length=64, blank=True)
    descricao = models.CharField(max_length=300, blank=True)
    retencao_ate = models.DateField(null=True, blank=True, help_text="Não pode ser excluído antes desta data.")

    class Meta:
        verbose_name = "anexo"
        verbose_name_plural = "anexos"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.nome

    @staticmethod
    def tipo_por_nome(nome: str) -> str:
        ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
        return {
            "xml": "XML",
            "pdf": "PDF",
            "png": "IMAGEM",
            "jpg": "IMAGEM",
            "jpeg": "IMAGEM",
            "webp": "IMAGEM",
            "xlsx": "PLANILHA",
            "csv": "PLANILHA",
            "ofx": "PLANILHA",
            "zip": "ZIP",
            "docx": "DOCX",
        }.get(ext, "OUTRO")

    @classmethod
    def criar(cls, objeto, nome: str, conteudo: bytes, descricao: str = "", tipo: str | None = None,
              retencao_anos: int | None = None, empresa=None):
        anexo = cls(
            nome=nome,
            tipo=tipo or cls.tipo_por_nome(nome),
            tamanho=len(conteudo),
            hash_sha256=hashlib.sha256(conteudo).hexdigest(),
            descricao=descricao,
        )
        if empresa is not None:
            anexo.empresa = empresa
        elif objeto is not None and getattr(objeto, "empresa_id", None):
            anexo.empresa_id = objeto.empresa_id
        if objeto is not None:
            anexo.content_type = ContentType.objects.get_for_model(objeto)
            anexo.object_id = str(objeto.pk)
        if retencao_anos:
            hoje = timezone.localdate()
            anexo.retencao_ate = hoje.replace(year=hoje.year + retencao_anos)
        anexo.arquivo.save(nome, ContentFile(conteudo), save=False)
        anexo.save()
        return anexo

    @classmethod
    def de_upload(cls, objeto, arquivo, descricao=""):
        conteudo = arquivo.read()
        return cls.criar(objeto, arquivo.name, conteudo, descricao=descricao)

    def ler(self) -> bytes:
        with self.arquivo.open("rb") as f:
            return f.read()

    def delete(self, *args, **kwargs):
        if self.retencao_ate and self.retencao_ate > timezone.localdate():
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(f"Documento sob retenção legal até {self.retencao_ate:%d/%m/%Y}.")
        return super().delete(*args, **kwargs)


class Parametro(ModeloBase):
    chave = models.CharField(max_length=100)
    valor = models.JSONField(default=dict, blank=True)
    descricao = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "parâmetro"
        verbose_name_plural = "parâmetros"
        constraints = [models.UniqueConstraint(fields=["empresa", "chave"], name="parametro_unico_empresa")]
        ordering = ["chave"]

    def __str__(self):
        return self.chave

    @classmethod
    def get(cls, chave, padrao=None, empresa=None):
        empresa = empresa or contexto.empresa_atual()
        p = cls.objects.filter(empresa=empresa, chave=chave).first() if empresa else None
        return p.valor if p is not None else padrao

    @classmethod
    def definir(cls, chave, valor, descricao="", empresa=None):
        empresa = empresa or contexto.empresa_atual()
        p, _ = cls.objects.update_or_create(
            empresa=empresa, chave=chave, defaults={"valor": valor, "descricao": descricao or ""}
        )
        return p


class Notificacao(ModeloSimples):
    class Nivel(models.TextChoices):
        INFO = "info", "Informação"
        SUCESSO = "success", "Sucesso"
        ATENCAO = "warning", "Atenção"
        PERIGO = "danger", "Crítico"

    class Canal(models.TextChoices):
        APP = "APP", "Aplicativo"
        EMAIL = "EMAIL", "E-mail"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notificacoes")
    titulo = models.CharField(max_length=200)
    mensagem = models.TextField(blank=True)
    nivel = models.CharField(max_length=10, choices=Nivel.choices, default=Nivel.INFO)
    link = models.CharField(max_length=300, blank=True)
    lida_em = models.DateTimeField(null=True, blank=True)
    canal = models.CharField(max_length=10, choices=Canal.choices, default=Canal.APP)
    chave_dedup = models.CharField(max_length=200, blank=True, db_index=True)

    class Meta:
        verbose_name = "notificação"
        verbose_name_plural = "notificações"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.titulo


class Segredo(ModeloSimples):
    class Escopo(models.TextChoices):
        FISCAL = "FISCAL", "Fiscal"
        IA = "IA", "IA"
        INTEGRACAO = "INTEGRACAO", "Integração"

    nome = models.CharField(max_length=100)
    valor_criptografado = models.BinaryField(editable=False)
    escopo = models.CharField(max_length=12, choices=Escopo.choices, default=Escopo.INTEGRACAO)
    rotacionado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "segredo"
        verbose_name_plural = "segredos"

    def __str__(self):
        return f"{self.nome} ({self.get_escopo_display()})"

    def definir(self, valor: str | bytes):
        self.valor_criptografado = cifrar(valor)
        self.rotacionado_em = timezone.now()

    def ler(self) -> str:
        return decifrar_texto(self.valor_criptografado)

    @classmethod
    def criar(cls, nome, valor, escopo="INTEGRACAO", empresa=None):
        s = cls(nome=nome, escopo=escopo)
        if empresa:
            s.empresa = empresa
        s.definir(valor)
        s.save()
        return s


class LogIntegracao(ModeloSimples):
    class Servico(models.TextChoices):
        SEFIN = "SEFIN", "Sefin Nacional"
        ADN = "ADN", "ADN Nacional"
        EL_ABRASF = "EL_ABRASF", "E&L ABRASF"
        EL_ACEITES = "EL_ACEITES", "E&L Aceites"
        GEMINI = "GEMINI", "Gemini"
        BRASILAPI = "BRASILAPI", "BrasilAPI"
        VIACEP = "VIACEP", "ViaCEP"
        SLA = "SLA", "Monitoramento"
        EMAIL = "EMAIL", "E-mail"

    servico = models.CharField(max_length=12, choices=Servico.choices)
    operacao = models.CharField(max_length=60)
    chave_idempotencia = models.CharField(max_length=120, blank=True, db_index=True)
    request = models.TextField(blank=True)
    response = models.TextField(blank=True)
    status_http = models.PositiveSmallIntegerField(null=True, blank=True)
    duracao_ms = models.PositiveIntegerField(null=True, blank=True)
    sucesso = models.BooleanField(default=False)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=40, blank=True)
    objeto = GenericForeignKey("content_type", "object_id")

    class Meta:
        verbose_name = "log de integração"
        verbose_name_plural = "logs de integração"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.servico}.{self.operacao} ({'ok' if self.sucesso else 'falha'})"


class LogAcesso(ModeloSimples):
    """Registro de acesso a documentos fiscais e financeiros (seção 12)."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    acao = models.CharField(max_length=40)
    content_type = models.ForeignKey(ContentType, null=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=40, blank=True)
    objeto = GenericForeignKey("content_type", "object_id")
    descricao = models.CharField(max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "log de acesso"
        verbose_name_plural = "logs de acesso"
        ordering = ["-criado_em"]
