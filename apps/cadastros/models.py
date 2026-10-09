from django.db import models

from apps.core.models import Endereco, ModeloBase
from apps.core.validadores import formatar_doc, so_digitos, validar_cpf_cnpj


class Pessoa(ModeloBase):
    """Cadastro único de clientes, órgãos públicos e fornecedores (seção 5.2)."""

    class Tipo(models.TextChoices):
        FISICA = "F", "Pessoa física"
        JURIDICA = "J", "Pessoa jurídica"

    class Esfera(models.TextChoices):
        MUNICIPAL = "MUNICIPAL", "Municipal"
        ESTADUAL = "ESTADUAL", "Estadual"
        FEDERAL = "FEDERAL", "Federal"

    tipo = models.CharField(max_length=1, choices=Tipo.choices, default=Tipo.JURIDICA)
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=14, validators=[validar_cpf_cnpj])
    razao_social = models.CharField("razão social / nome", max_length=200)
    nome_fantasia = models.CharField(max_length=200, blank=True)
    situacao_cadastral = models.CharField("situação cadastral", max_length=100, blank=True)
    data_abertura = models.DateField("data de abertura", null=True, blank=True)
    cnae_principal = models.CharField("CNAE principal", max_length=10, blank=True)
    descricao_cnae = models.CharField("descrição do CNAE", max_length=300, blank=True)
    natureza_juridica = models.CharField("natureza jurídica", max_length=200, blank=True)
    porte = models.CharField("porte da empresa", max_length=100, blank=True)
    inscricao_municipal = models.CharField("inscrição municipal", max_length=30, blank=True)
    inscricao_estadual = models.CharField("inscrição estadual", max_length=30, blank=True)
    e_orgao_publico = models.BooleanField("é órgão público", default=False)
    esfera = models.CharField(max_length=10, choices=Esfera.choices, blank=True)
    endereco = models.ForeignKey(Endereco, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.EmailField("e-mail", blank=True)
    email_nf = models.EmailField("e-mail para NF", blank=True, help_text="Destino do envio automático da nota.")
    telefone = models.CharField(max_length=30, blank=True)
    eh_cliente = models.BooleanField("cliente", default=True)
    eh_fornecedor = models.BooleanField("fornecedor", default=False)
    optante_simples = models.BooleanField("optante do Simples", null=True, blank=True)
    observacoes = models.TextField("observações", blank=True)
    finalidade_dados = models.CharField("finalidade do tratamento (LGPD)", max_length=200, blank=True,
                                        default="Execução de contrato e obrigações fiscais")

    class Meta:
        verbose_name = "pessoa"
        verbose_name_plural = "clientes e fornecedores"
        ordering = ["razao_social"]
        constraints = [models.UniqueConstraint(fields=["empresa", "cpf_cnpj"], name="pessoa_doc_unico_empresa")]

    def __str__(self):
        return self.nome_fantasia or self.razao_social

    def save(self, *args, **kwargs):
        self.cpf_cnpj = so_digitos(self.cpf_cnpj)
        self.tipo = "F" if len(self.cpf_cnpj) == 11 else "J"
        super().save(*args, **kwargs)

    @property
    def doc_formatado(self):
        return formatar_doc(self.cpf_cnpj)

    @property
    def email_destino_nf(self):
        return self.email_nf or self.email

    def snapshot(self) -> dict:
        """Dados congelados no momento da emissão da nota (tomador_snapshot)."""
        e = self.endereco
        return {
            "cpf_cnpj": self.cpf_cnpj,
            "razao_social": self.razao_social,
            "inscricao_municipal": self.inscricao_municipal,
            "email": self.email_destino_nf,
            "telefone": self.telefone,
            "cep": e.cep if e else "",
            "tipo_logradouro": e.tipo_logradouro if e else "",
            "logradouro": e.logradouro if e else "",
            "numero": e.numero if e else "",
            "complemento": e.complemento if e else "",
            "bairro": e.bairro if e else "",
            "municipio_ibge": e.municipio_ibge if e else "",
            "municipio_nome": e.municipio_nome if e else "",
            "uf": e.uf if e else "",
        }

    def anonimizar(self):
        """Atende solicitação de remoção (LGPD) de pessoa física sem documentos fiscais."""
        self.razao_social = "Titular anonimizado"
        self.nome_fantasia = ""
        self.email = self.email_nf = self.telefone = ""
        self.observacoes = ""
        self.ativo = False
        self.save()


class Contato(ModeloBase):
    pessoa = models.ForeignKey(Pessoa, on_delete=models.CASCADE, related_name="contatos")
    nome = models.CharField(max_length=150)
    cargo = models.CharField(max_length=100, blank=True, help_text='Ex.: "Fiscal do contrato", "Gestor", "Financeiro"')
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    recebe_relatorios = models.BooleanField(default=False)

    class Meta:
        verbose_name = "contato"
        verbose_name_plural = "contatos"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.cargo})" if self.cargo else self.nome
