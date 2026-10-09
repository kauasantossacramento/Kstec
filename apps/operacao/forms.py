from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.contratos.views import contratos_visiveis
from apps.core.forms import FormKS, FormSimples

from .models import Tarefa
from .services import validar


class TarefaForm(FormKS):
    aceita_request = True

    class Meta:
        model = Tarefa
        fields = ["contrato", "titulo", "descricao", "tipo", "prioridade", "responsavel", "solicitante",
                  "protocolo_cliente", "data_abertura", "prazo", "horas_estimadas", "entrar_no_relatorio", "resumo_para_relatorio"]

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields["contrato"].queryset = contratos_visiveis(request.user, self.fields["contrato"].queryset.filter(empresa=request.empresa))
        self.fields["responsavel"].queryset = self.fields["responsavel"].queryset.filter(empresa=request.empresa, is_active=True)
        if not request.user.tem_papel("Administrador"):
            self.fields["responsavel"].queryset = self.fields["responsavel"].queryset.filter(pk=request.user.pk)
        self.fields["responsavel"].initial = request.user.pk

    def clean(self):
        dados = super().clean()
        if not self.errors:
            self.instance.empresa = self.request.empresa
            for nome, valor in dados.items():
                setattr(self.instance, nome, valor)
            try:
                validar(self.instance, self.request.user)
            except ValidationError as erro:
                self.add_error(None, erro)
        return dados


class ApontamentoForm(FormSimples):
    data = forms.DateField(initial=timezone.localdate)
    horas = forms.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0.01"), max_value=24)
    descricao = forms.CharField(label="Descrição da atividade", widget=forms.Textarea)
