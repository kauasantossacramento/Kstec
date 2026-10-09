from apps.contratos.abas import aba

from .models import NotaFiscal


@aba("notas")
def notas(request, contrato):
    if not request.user.tem_papel("Administrador", "Fiscal", "Financeiro", "Leitura"):
        return "financeiro/aba_restrita.html", {}
    return "fiscal/aba_contrato.html", {"notas": NotaFiscal.objects.filter(empresa=request.empresa, contrato=contrato)}
