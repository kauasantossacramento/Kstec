from apps.contratos.abas import aba

from .services.monitor import uptime_diario


@aba("sla")
def sistemas(request, contrato):
    lista = list(contrato.sistemas.filter(ativo=True))
    for s in lista:
        s.barras = uptime_diario(s, 30)
    return "sla/aba_contrato.html", {"sistemas": lista, "contrato": contrato}
