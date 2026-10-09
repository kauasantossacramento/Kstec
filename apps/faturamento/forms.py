from django import forms
from django.core.exceptions import ValidationError

from apps.catalogo.models import ItemCatalogo
from apps.contratos.models import Contrato, Empenho
from apps.core.forms import FormKS

from .models import AgendaFaturamento, AjustePrevisao, CicloFaturamento

RADIOS = ("referencia", "tipo_vencimento", "modo")


class AgendaForm(FormKS):
    aceite_automatico = forms.BooleanField(
        label="Entendo que a nota será transmitida sem revisão prévia, no horário programado.", required=False)

    PASSOS = [
        ("Contrato e serviço", "file-text", "Qual contrato será faturado e com qual serviço do catálogo.",
         ["contrato", "item_catalogo", "perfil", "empenho"]),
        ("Valor e descrição", "receipt", "O valor mensal e o texto que vai na nota. Ajustes de um mês específico "
         "são feitos depois, no próprio ciclo.", ["valor", "discriminacao"]),
        ("Calendário", "calendar", "Quando emitir, qual competência faturar e quando vence.",
         ["referencia", "dia_emissao", "hora_emissao", "dia_util", "tipo_vencimento", "prazo_dias",
          "dia_vencimento", "inicio", "fim"]),
        ("Automação", "zap", "Quanto do processo o sistema faz sozinho. Você pode mudar a qualquer momento.",
         ["modo", "aceite_automatico", "enviar_whatsapp", "gerar_cobranca", "observacoes"]),
    ]
    DESCRICOES = {
        "referencia": {"MES_ANTERIOR": "Em novembro emite a competência de outubro. Padrão para serviços mensais.",
                       "MES_CORRENTE": "Em novembro emite a competência de novembro."},
        "tipo_vencimento": {"PRAZO": "Vencimento = data da emissão + prazo do contrato.",
                            "DIA_FIXO": "Sempre no mesmo dia; se já passou, no mês seguinte."},
        "modo": {"RASCUNHO": "Calcula a nota e avisa. Você revisa e transmite pela tela da nota.",
                 "CONFIRMAR": "Valida tudo e pede sua confirmação aqui ou no WhatsApp (SIM + código). Recomendado.",
                 "AUTOMATICO": "Transmite no horário se todas as validações passarem. Bloqueios são avisados."},
    }
    CONDICIONAIS = {"prazo_dias": "tipo_vencimento=PRAZO", "dia_vencimento": "tipo_vencimento=DIA_FIXO",
                    "aceite_automatico": "modo=AUTOMATICO"}
    LARGOS = {"contrato", "discriminacao", "observacoes", "aceite_automatico", "enviar_whatsapp", "gerar_cobranca",
              "dia_util"}

    class Meta:
        model = AgendaFaturamento
        fields = ["contrato", "item_catalogo", "perfil", "empenho", "valor", "discriminacao", "referencia",
                  "dia_emissao", "hora_emissao", "dia_util", "tipo_vencimento", "prazo_dias", "dia_vencimento",
                  "inicio", "fim", "modo", "enviar_whatsapp", "gerar_cobranca", "observacoes"]
        widgets = {"referencia": forms.RadioSelect, "tipo_vencimento": forms.RadioSelect, "modo": forms.RadioSelect,
                   "hora_emissao": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "discriminacao": forms.Textarea(attrs={"rows": 4}), "observacoes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome in RADIOS:
            self.fields[nome].widget.attrs["class"] = "radio"
        contratos = self.fields["contrato"].queryset.filter(status=Contrato.Status.VIGENTE)
        if self.instance.pk and not self.instance._state.adding:
            self.fields["contrato"].disabled = True
            contratos = self.fields["contrato"].queryset.filter(pk=self.instance.contrato_id)
        else:
            contratos = contratos.filter(agenda_faturamento__isnull=True)
        self.fields["contrato"].queryset = contratos.select_related("cliente")
        self.fields["item_catalogo"].queryset = self.fields["item_catalogo"].queryset.filter(ativo=True)
        self.fields["empenho"].queryset = self.fields["empenho"].queryset.select_related("contrato")
        self.fields["empenho"].label_from_instance = lambda e: f"{e.numero} · contrato {e.contrato.numero}"
        self.fields["inicio"].help_text = "Primeiro mês de serviço que será faturado por esta agenda."
        self.fields["dia_emissao"].help_text = "Meses mais curtos usam o último dia disponível."
        self.fields["prazo_dias"].required = False

    def opcoes(self, nome):
        bf = self[nome]
        atual = str(bf.value() or "")
        return [{"valor": v, "rotulo": r, "desc": self.DESCRICOES[nome].get(v, ""), "checked": str(v) == atual,
                 "id": f"id_{nome}_{i}", "recomendado": nome == "modo" and v == "CONFIRMAR"}
                for i, (v, r) in enumerate(self.fields[nome].choices) if v != ""]

    def passos(self):
        saida = []
        for i, (titulo, icone, descricao, campos) in enumerate(self.PASSOS, 1):
            itens = [{"bf": self[c], "opcoes": self.opcoes(c) if c in RADIOS else None, "largo": c in self.LARGOS,
                      "mostrar_se": self.CONDICIONAIS.get(c, ""), "placeholders": c == "discriminacao"}
                     for c in campos]
            saida.append({"numero": i, "titulo": titulo, "icone": icone, "descricao": descricao, "campos": itens,
                          "erros": any(self[c].errors for c in campos)})
        return saida

    def clean(self):
        d = super().clean()
        contrato = d.get("contrato") or getattr(self.instance, "contrato", None)
        if d.get("empenho") and contrato and d["empenho"].contrato_id != contrato.pk:
            self.add_error("empenho", "O empenho deve pertencer ao contrato selecionado.")
        if d.get("inicio") and contrato:
            inicio = d["inicio"].replace(day=1)
            d["inicio"] = inicio
            if not contrato.vigencia_inicio.replace(day=1) <= inicio <= contrato.vigencia_fim_atual:
                self.add_error("inicio", "A primeira competência precisa estar dentro da vigência do contrato.")
        if d.get("fim"):
            d["fim"] = d["fim"].replace(day=1)
            if d.get("inicio") and d["fim"] < d["inicio"]:
                self.add_error("fim", "A última competência deve ser igual ou posterior à primeira.")
        if d.get("prazo_dias") is None:
            d["prazo_dias"] = 30
        if d.get("tipo_vencimento") == AgendaFaturamento.Vencimento.DIA_FIXO and not d.get("dia_vencimento"):
            self.add_error("dia_vencimento", "Informe o dia do vencimento.")
        if d.get("modo") == AgendaFaturamento.Modo.AUTOMATICO and not d.get("aceite_automatico"):
            self.add_error("aceite_automatico", "Confirme que entende a transmissão automática.")
        item = d.get("item_catalogo")
        if isinstance(item, ItemCatalogo) and item.pendencias_fiscais:
            self.add_error("item_catalogo", item.pendencias_fiscais)
        return d


class CicloForm(FormKS):
    class Meta:
        model = CicloFaturamento
        fields = ["valor", "data_emissao", "data_vencimento", "discriminacao"]
        widgets = {"discriminacao": forms.Textarea(attrs={"rows": 3})}


class AjustePrevisaoForm(FormKS):
    class Meta:
        model = AjustePrevisao
        fields = ["data_prevista", "valor", "excluir", "motivo"]

    def __init__(self, *args, mes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mes = mes
        self.fields["motivo"].widget.attrs["placeholder"] = "Ex.: empenho atrasado; pagamento combinado para dia 20"

    def clean(self):
        d = super().clean()
        if not d.get("excluir") and not d.get("data_prevista") and d.get("valor") is None:
            raise ValidationError("Informe nova data, novo valor ou marque para não considerar neste mês.")
        return d


def contratos_json(empresa):
    """Dados para pré-preencher o wizard ao escolher o contrato."""
    saida = {}
    for c in Contrato.objects.filter(empresa=empresa, status=Contrato.Status.VIGENTE).select_related("cliente"):
        saida[str(c.pk)] = {
            "valor": str(c.valor_mensal or ""), "dia": c.dia_faturamento or 1, "prazo": c.prazo_pagamento_dias,
            "inicio": c.vigencia_inicio.replace(day=1).isoformat(), "fim": c.vigencia_fim_atual.isoformat(),
            "discriminacao": c.discriminacao_padrao, "cliente": str(c.cliente), "numero": c.numero,
            "saldo": str(c.saldo), "objeto": c.objeto[:300],
            "empenhos": list(Empenho.objects.filter(contrato=c).values_list("pk", flat=True).iterator()),
        }
    for v in saida.values():
        v["empenhos"] = [str(e) for e in v["empenhos"]]
    return saida
