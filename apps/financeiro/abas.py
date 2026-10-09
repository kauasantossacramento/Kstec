from django.utils import timezone

from apps.contratos.abas import aba

from .models import Lancamento
from .services.relatorios import dre


@aba("financeiro")
def financeiro(request, contrato):
    if not request.user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        return "financeiro/aba_restrita.html", {}
    hoje = timezone.localdate()
    return "financeiro/aba_contrato.html", {
        "lancamentos": Lancamento.objects.filter(empresa=request.empresa, centro_custo__contrato=contrato),
        "resultado": dre(request.empresa, contrato.vigencia_inicio, hoje, contrato) if contrato.vigencia_inicio <= hoje else None,
    }


@aba("custos")
def custos(request, contrato):
    if not request.user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        return "financeiro/aba_restrita.html", {}
    return "fiscal/aba_documentos_contrato.html", {"contrato": contrato,
                  "documentos": contrato.planilhas_custos.all(), "tipo_documento": "Planilhas de custos"}
