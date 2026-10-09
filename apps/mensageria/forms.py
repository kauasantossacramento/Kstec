from django import forms
from django.core.exceptions import ValidationError

from apps.core.forms import FormKS
from apps.core.validadores import normalizar_telefone

from .models import ConfiguracaoWhatsApp, ContatoWhatsApp


class ConfiguracaoWhatsAppForm(FormKS):
    SECOES = [
        ("Conexão e administradores", "Quem recebe alertas e pode comandar o sistema pelo WhatsApp.",
         ["ativo", "transporte", "numeros_admin", "comandos"]),
        ("Ritmo seguro", "Limites que imitam um uso humano e reduzem o risco de bloqueio do número.",
         ["horario_inicio", "horario_fim", "dias_uteis", "limite_hora", "limite_dia", "intervalo_min", "intervalo_max",
          "novos_por_dia", "simular_digitacao"]),
        ("Confirmação de envios", "Antes de enviar a clientes, você recebe o resumo com os arquivos e responde SIM ou NAO.",
         ["confirmar_envios", "prazo_confirmacao_h", "sem_resposta"]),
        ("Automações", "O que o sistema envia sozinho.",
         ["avisos_faturamento", "alertas_monitoramento", "lembretes_cobranca", "hora_lembretes", "resumo_diario",
          "hora_resumo"]),
        ("Assistente com IA", "Perguntas em linguagem natural pelos seus números: monitoramento, receitas, notas, despesas. "
         "Ações que gravam dados sempre pedem SIM + código.", ["assistente_ia", "modelo_ia", "nova_chave_gemini"]),
    ]
    nova_chave_gemini = forms.CharField(label="Chave da API Gemini", required=False,
                                        widget=forms.PasswordInput(render_value=False),
                                        help_text="Google AI Studio → Get API key. Em branco mantém a atual; fica cifrada.")

    class Meta:
        model = ConfiguracaoWhatsApp
        fields = ["ativo", "transporte", "numeros_admin", "comandos", "horario_inicio", "horario_fim", "dias_uteis",
                  "limite_hora", "limite_dia", "intervalo_min", "intervalo_max", "novos_por_dia", "simular_digitacao",
                  "confirmar_envios", "prazo_confirmacao_h", "sem_resposta", "avisos_faturamento",
                  "alertas_monitoramento", "lembretes_cobranca", "hora_lembretes", "resumo_diario", "hora_resumo",
                  "assistente_ia", "modelo_ia"]
        labels = {"ativo": "WhatsApp ativo"}
        widgets = {campo: forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
                   for campo in ("horario_inicio", "horario_fim", "hora_lembretes", "hora_resumo")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numeros_admin"].widget.attrs["placeholder"] = "(75) 99999-0000"
        self.fields["modelo_ia"].required = False

    def clean_modelo_ia(self):
        return (self.cleaned_data.get("modelo_ia") or "").strip() or "gemini-flash-latest"

    def secoes(self):
        largos = {"numeros_admin", "ativo", "comandos", "dias_uteis", "simular_digitacao", "confirmar_envios",
                  "avisos_faturamento", "alertas_monitoramento", "lembretes_cobranca", "resumo_diario", "assistente_ia",
                  "nova_chave_gemini"}
        return [{"titulo": t, "descricao": d, "campos": [{"bf": self[c], "largo": c in largos} for c in campos]}
                for t, d, campos in self.SECOES]

    def clean_numeros_admin(self):
        valor = self.cleaned_data["numeros_admin"]
        partes = [p.strip() for p in valor.split(",") if p.strip()]
        invalidos = [p for p in partes if not normalizar_telefone(p)]
        if invalidos:
            raise ValidationError(f"Número inválido: {', '.join(invalidos)}. Use DDD + número.")
        return ", ".join(normalizar_telefone(p) for p in partes)

    def clean(self):
        d = super().clean()
        if d.get("intervalo_min") and d.get("intervalo_max") and d["intervalo_max"] < d["intervalo_min"]:
            self.add_error("intervalo_max", "Deve ser maior ou igual ao intervalo mínimo.")
        if d.get("horario_inicio") and d.get("horario_fim") and d["horario_fim"] <= d["horario_inicio"]:
            self.add_error("horario_fim", "O fim da janela deve ser depois do início.")
        if d.get("assistente_ia") and not (d.get("nova_chave_gemini") or self.instance.gemini_chave_id):
            self.add_error("nova_chave_gemini", "Informe a chave da API Gemini para ativar o assistente.")
        if d.get("ativo") and d.get("transporte") == "NEONIZE" and not d.get("numeros_admin"):
            self.add_error("numeros_admin", "Informe ao menos um número de administrador.")
        return d


class ContatoForm(FormKS):
    class Meta:
        model = ContatoWhatsApp
        fields = ["pessoa", "nome", "telefone", "consentimento", "origem_consentimento", "recebe_notas",
                  "recebe_cobrancas", "ativo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["telefone"].widget.attrs.update({"placeholder": "(75) 99999-0000", "inputmode": "tel"})

    def clean(self):
        d = super().clean()
        if d.get("consentimento") and not (d.get("origem_consentimento") or "").strip():
            self.add_error("origem_consentimento", "Registre como o cliente autorizou (LGPD).")
        return d
