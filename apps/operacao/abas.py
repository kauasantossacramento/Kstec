from apps.contratos.abas import aba
from apps.core.permissoes import pode_escrever

from .services import visiveis


@aba("tarefas")
def tarefas(request, contrato):
    return "operacao/aba_tarefas.html", {"tarefas": visiveis(request.user, request.empresa).filter(contrato=contrato),
                                       "pode_criar_tarefa": pode_escrever(request.user, ["Operação"])}


@aba("relatorios")
def relatorios(request, contrato):
    return "fiscal/aba_documentos_contrato.html", {"contrato": contrato,
                  "documentos": contrato.relatorios_atividades.all(), "tipo_documento": "Relatórios de atividades"}
