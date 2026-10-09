from django import forms

from apps.core.forms import FormKS

from .models import ConfiguracaoAsaas, PerfilCobranca


class ConfiguracaoAsaasForm(FormKS):
    nova_api_key = forms.CharField(label="Chave de API", required=False, widget=forms.PasswordInput(render_value=False),
                                   help_text="Asaas → Integrações → Chave de API. Deixe em branco para manter a atual.")

    class Meta:
        model = ConfiguracaoAsaas
        fields = ["ambiente", "forma_padrao", "multa_pct", "juros_mes_pct", "baixa_automatica", "conta_recebimento",
                  "ativo"]
        labels = {"ativo": "Integração ativa"}


class PerfilCobrancaForm(FormKS):
    class Meta:
        model = PerfilCobranca
        fields = ["whatsapp_ativo", "enviar_nota", "enviar_lembretes", "dias_antes", "dias_depois", "link_pagamento",
                  "forma", "confirmacao"]
