from apps.contratos.abas import ABAS, aba

from .services import ciclos

if ("faturamento", "Faturamento") not in ABAS:
    ABAS.insert(2, ("faturamento", "Faturamento"))


@aba("faturamento")
def faturamento(request, contrato):
    if not request.user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        return "financeiro/aba_restrita.html", {}
    agenda = getattr(contrato, "agenda_faturamento", None)
    return "faturamento/aba_contrato.html", {
        "agenda": agenda, "contrato": contrato,
        "ciclos": agenda.ciclos.select_related("nota").order_by("-competencia")[:12] if agenda else [],
        "proxima": ciclos.proxima_execucao(agenda) if agenda and agenda.ativo else None,
    }
