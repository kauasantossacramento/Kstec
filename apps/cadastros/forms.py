from django import forms
from django.urls import reverse_lazy

from apps.core.forms import FormKS
from apps.core.models import Endereco
from apps.core.validadores import so_digitos

from .models import Contato, Pessoa

CAMPOS_ENDERECO = ["cep", "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "municipio_ibge",
                   "municipio_nome", "uf"]


class PessoaForm(FormKS):
    """Pessoa + endereço em um só formulário. Digitar o CNPJ preenche o restante (BrasilAPI)."""

    cep = forms.CharField(label="CEP", max_length=9, required=False)
    tipo_logradouro = forms.CharField(label="Tipo de logradouro", max_length=30, required=False)
    logradouro = forms.CharField(max_length=200, required=False)
    numero = forms.CharField(label="Número", max_length=20, required=False)
    complemento = forms.CharField(max_length=100, required=False)
    bairro = forms.CharField(max_length=100, required=False)
    municipio_ibge = forms.CharField(label="Código IBGE do município", max_length=7, required=False)
    municipio_nome = forms.CharField(label="Município", max_length=100, required=False)
    uf = forms.CharField(label="UF", max_length=2, required=False)

    class Meta:
        model = Pessoa
        fields = ["cpf_cnpj", "razao_social", "nome_fantasia", "inscricao_municipal", "inscricao_estadual",
                  "email", "email_nf", "telefone", "eh_cliente", "eh_fornecedor", "e_orgao_publico", "esfera",
                  "optante_simples", "situacao_cadastral", "data_abertura", "cnae_principal", "descricao_cnae",
                  "natureza_juridica", "porte", "observacoes"]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["cpf_cnpj"].widget.attrs["data-consulta-cnpj"] = reverse_lazy("core:consulta_cnpj")
        self.fields["cpf_cnpj"].widget.attrs["autofocus"] = True
        self.fields["cpf_cnpj"].help_text = "Digite o CNPJ e saia do campo ou clique em Consultar CNPJ. Confira os dados antes de salvar."
        self.fields["cep"].widget.attrs["data-consulta-cep"] = reverse_lazy("core:consulta_cep")
        e = self.instance.endereco if self.instance.pk else None
        if e:
            for c in CAMPOS_ENDERECO:
                self.fields[c].initial = getattr(e, c)

    def clean_cpf_cnpj(self):
        doc = so_digitos(self.cleaned_data["cpf_cnpj"])
        from apps.core import contexto

        qs = Pessoa.objects.filter(cpf_cnpj=doc, empresa=contexto.empresa_atual())
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe cadastro com este CPF/CNPJ.")
        return doc

    def clean(self):
        dados = super().clean()
        if dados.get("e_orgao_publico") and not dados.get("esfera"):
            self.add_error("esfera", "Informe a esfera do órgão público.")
        return dados

    def save(self, commit=True):
        pessoa = super().save(commit=False)
        dados_end = {c: self.cleaned_data.get(c) or "" for c in CAMPOS_ENDERECO}
        if dados_end["cep"] or dados_end["logradouro"]:
            end = pessoa.endereco or Endereco()
            for c, v in dados_end.items():
                setattr(end, c, v)
            end.numero = end.numero or "S/N"
            end.save()
            pessoa.endereco = end
        if commit:
            pessoa.save()
        return pessoa


class ContatoForm(FormKS):
    class Meta:
        model = Contato
        fields = ["pessoa", "nome", "cargo", "email", "telefone", "recebe_relatorios"]
