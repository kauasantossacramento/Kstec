from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core import contexto
from apps.core.forms import FormKS, FormSimples

from .models import CategoriaFinanceira, ContaBancaria, Lancamento, Recorrencia
from .services.lancamentos import validar


class LancamentoForm(FormKS):
    class Meta:
        model = Lancamento
        fields = ["tipo", "descricao", "pessoa", "categoria", "centro_custo", "conta_bancaria", "valor",
                  "data_competencia", "data_vencimento"]

    def clean(self):
        dados = super().clean()
        if not self.errors:
            self.instance.empresa = contexto.empresa_atual()
            for k, v in dados.items():
                setattr(self.instance, k, v)
            try:
                validar(self.instance)
            except ValidationError as erro:
                self.add_error(None, erro)
        return dados


class CategoriaForm(FormKS):
    class Meta:
        model = CategoriaFinanceira
        fields = ["nome", "tipo", "grupo_dre", "ativo"]

    def clean(self):
        dados = super().clean()
        from .services.lancamentos import validar_categoria

        if not self.errors:
            validar_categoria(dados["tipo"], dados["grupo_dre"])
            if not self.instance._state.adding and self.instance.lancamento_set.exists():
                if dados["tipo"] != self.instance.tipo or dados["grupo_dre"] != self.instance.grupo_dre:
                    raise ValidationError("Categorias utilizadas não podem mudar de tipo ou grupo do demonstrativo.")
        return dados


class RecorrenciaForm(FormKS):
    class Meta:
        model = Recorrencia
        fields = ["descricao", "tipo", "pessoa", "categoria", "centro_custo", "conta_bancaria", "valor",
                  "frequencia", "dia", "inicio", "fim", "ativo"]

    def clean(self):
        dados = super().clean()
        if not self.errors:
            from .services.recorrencias import validar_recorrencia

            self.instance.empresa = contexto.empresa_atual()
            for nome, valor in dados.items():
                setattr(self.instance, nome, valor)
            try:
                validar_recorrencia(self.instance)
            except ValidationError as erro:
                self.add_error(None, erro)
        return dados


class BaixaForm(FormSimples):
    conta_bancaria = forms.ModelChoiceField(ContaBancaria.objects.filter(ativo=True), required=False, label="Conta do pagamento")
    data_pagamento = forms.DateField(label="Data do pagamento", initial=timezone.localdate)
    forma_pagamento = forms.ChoiceField(label="Forma de pagamento", choices=Lancamento.Forma.choices)
    juros = forms.DecimalField(max_digits=14, decimal_places=2, initial=0, min_value=0)
    multa = forms.DecimalField(max_digits=14, decimal_places=2, initial=0, min_value=0)
    desconto = forms.DecimalField(max_digits=14, decimal_places=2, initial=0, min_value=0)
    ordem_bancaria = forms.CharField(label="Ordem bancária", max_length=100, required=False)
    data_liquidacao = forms.DateField(label="Data da liquidação", required=False)


class ExtratoForm(FormSimples):
    conta = forms.ModelChoiceField(ContaBancaria.objects.filter(ativo=True), label="Conta bancária")
    arquivo = forms.FileField(label="Extrato CSV / OFX")
