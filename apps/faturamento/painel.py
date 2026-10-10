from django.urls import reverse
from django.utils import timezone

from apps.core.agenda import Evento, ItemAtencao, agenda, atencao

from .models import CicloFaturamento

S = CicloFaturamento.Status


@agenda
def emissoes(empresa, inicio, fim):
    qs = CicloFaturamento.objects.filter(empresa=empresa, data_emissao__range=(inicio, fim),
                                         agenda__ativo=True).exclude(status=S.PULADO).select_related("agenda__contrato")
    return [Evento(c.data_emissao, f"Emissão NFS-e · {c.agenda.contrato.numero}", "FISCAL",
                   reverse("faturamento:ciclo", args=[c.pk]),
                   "success" if c.status == S.AUTORIZADO else "danger" if c.status in (S.BLOQUEADO, S.FALHA) else "info",
                   str(c.valor)) for c in qs]


@atencao
def pendencias(empresa, usuario):
    if not usuario.tem_papel("Administrador", "Fiscal", "Financeiro", "Leitura"):
        return []
    itens = []
    url = reverse("faturamento:home")
    aguardando = CicloFaturamento.objects.filter(empresa=empresa, status=S.AGUARDANDO, agenda__ativo=True).count()
    if aguardando:
        itens.append(ItemAtencao(f"{aguardando} emissão(ões) aguardando sua confirmação", url, "warning", 5,
                                 icone="repeat"))
    bloqueados = CicloFaturamento.objects.filter(empresa=empresa, status__in=[S.BLOQUEADO, S.FALHA], agenda__ativo=True,
                                                 data_emissao__lte=timezone.localdate()).count()
    if bloqueados:
        itens.append(ItemAtencao(f"{bloqueados} faturamento(s) bloqueado(s) ou com falha", url, "danger", 4,
                                 icone="alert"))
    return itens
