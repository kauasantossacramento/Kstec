from django import forms

from apps.core.forms import FormKS, FormSimples
from apps.financeiro.models import ItemCusto, PlanilhaCustos
from apps.operacao.models import RelatorioAtividades

from .services.entregas import emails


class PrepararEntregaForm(FormSimples):
    destinatarios = forms.CharField(label="Destinatários", help_text="Separe e-mails por ponto e vírgula.", max_length=2000)
    assunto = forms.CharField(max_length=200)
    mensagem = forms.CharField(widget=forms.Textarea, max_length=10000)

    def clean_destinatarios(self):
        texto = self.cleaned_data["destinatarios"]
        emails(texto)
        return texto


class EnviarEntregaForm(FormSimples):
    confirmar = forms.BooleanField(label="Conferi os destinatários e os documentos deste envio.")


class RelatorioForm(FormKS):
    class Meta:
        model = RelatorioAtividades
        fields = ["introducao", "conteudo", "consideracoes_finais"]
        widgets = {"conteudo": forms.Textarea(attrs={"rows": 14})}


class PlanilhaForm(FormKS):
    class Meta:
        model = PlanilhaCustos
        fields = ["administracao_central", "seguro_garantia", "risco", "despesas_financeiras", "lucro", "tributos", "observacoes"]


class ItemCustoForm(FormKS):
    class Meta:
        model = ItemCusto
        fields = ["grupo", "descricao", "unidade", "quantidade", "valor_unitario", "rateio_pct", "periodicidade", "fonte"]


CustosFormSet = forms.formset_factory(ItemCustoForm, extra=3, max_num=100, validate_max=True)
