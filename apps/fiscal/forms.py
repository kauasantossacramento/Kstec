from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core import contexto
from apps.core.forms import FormKS, FormSimples

from .models import CertificadoDigital, ConfiguracaoFiscal, NotaFiscal
from .services.rascunhos import preparar


class NotaForm(FormKS):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk or self.instance._state.adding:
            config = ConfiguracaoFiscal.objects.filter(empresa=contexto.empresa_atual()).first()
            if config:
                self.initial.setdefault("perfil", config.perfil_padrao_id)
                self.initial.setdefault("aliquota_iss", config.aliquota_iss)
            self.initial.setdefault("competencia", timezone.localdate())
    class Meta:
        model = NotaFiscal
        fields = ["tomador", "contrato", "item_catalogo", "perfil", "competencia", "discriminacao",
                  "valor_servicos", "valor_deducoes", "desconto_incondicionado", "desconto_condicionado",
                  "outras_retencoes", "aliquota_iss", "vencimento_recebivel"]

    def clean(self):
        dados = super().clean()
        if not self.errors:
            self.instance.empresa = contexto.empresa_atual()
            for campo, valor in dados.items():
                setattr(self.instance, campo, valor)
            try:
                preparar(self.instance)
            except ValidationError as erro:
                self.add_error(None, erro)
        return dados


class ConfiguracaoForm(FormKS):
    token = forms.CharField(label="Novo token municipal", required=False, widget=forms.PasswordInput,
                           help_text="Deixe em branco para manter o token cadastrado.")
    arquivo = forms.FileField(label="Novo certificado A1 (.pfx ou .p12)", required=False)
    senha = forms.CharField(label="Senha do novo certificado", required=False, widget=forms.PasswordInput)

    class Meta:
        model = ConfiguracaoFiscal
        fields = ["canal_padrao", "ambiente", "serie_dps", "certificado", "perfil_padrao", "aliquota_iss",
                  "total_tributos_simples", "vigencia_inicio", "vigencia_fim", "fonte_tributacao",
                  "conta_recebimento", "prazo_recebimento_dias"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["certificado"].queryset = CertificadoDigital.objects.filter(empresa=self.instance.empresa, ativo=True)


class ConfirmarEmissaoForm(FormSimples):
    confirmar = forms.BooleanField(label="Conferi os dados e desejo transmitir esta nota no ambiente indicado.")
