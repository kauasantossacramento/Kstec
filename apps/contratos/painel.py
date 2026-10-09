from django.urls import reverse

from apps.core.agenda import Evento, ItemAtencao, agenda, atencao

from .models import Contrato
from .services import alertas_contrato


@agenda
def _agenda_contratos(empresa, inicio, fim):
    eventos = []
    for c in Contrato.objects.filter(empresa=empresa, status=Contrato.Status.VIGENTE).select_related("cliente"):
        fim_vig = c.vigencia_fim_atual
        if inicio <= fim_vig <= fim:
            eventos.append(Evento(fim_vig, f"Fim de vigência: contrato {c.numero}", "CONTRATO",
                                  reverse("contratos:contrato_detalhe", args=[c.pk]), "warning", str(c.cliente)))
    return eventos


@atencao
def _atencao_contratos(empresa, usuario):
    itens = []
    for c in Contrato.objects.filter(empresa=empresa, status=Contrato.Status.VIGENTE).select_related("cliente"):
        for a in alertas_contrato(c):
            itens.append(ItemAtencao(f"Contrato {c.numero}: {a['texto']}",
                                     reverse("contratos:contrato_detalhe", args=[c.pk]), a["nivel"],
                                     25 if a["nivel"] == "danger" else 45, str(c.cliente), "file-text"))
    return itens
