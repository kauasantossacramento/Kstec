"""Mapas de status → cor do badge (anexo 14.4). Cores: success, info, warning, danger, neutral."""

MAPAS = {
    "NotaFiscal": {
        "AUTORIZADA": "success",
        "NA_FILA": "info", "TRANSMITINDO": "info",
        "VALIDADA": "warning", "CANCELAMENTO_SOLICITADO": "warning", "ERRO_COMUNICACAO": "warning",
        "REJEITADA": "danger",
        "RASCUNHO": "neutral", "CANCELADA": "neutral", "SUBSTITUIDA": "neutral",
    },
    "Lancamento": {"PAGO": "success", "PREVISTO": "info", "PENDENTE": "warning", "ATRASADO": "danger",
                   "CANCELADO": "neutral"},
    "Certidao": {"VALIDA": "success", "VENCENDO": "warning", "VENCIDA": "danger"},
    "Sistema": {"OPERACIONAL": "success", "MANUTENCAO": "info", "DEGRADADO": "warning", "FORA": "danger",
                "DESCONHECIDO": "neutral"},
    "Orcamento": {"APROVADO": "success", "CONVERTIDO": "success", "ENVIADO": "info", "VISUALIZADO": "info",
                  "RECUSADO": "danger", "RASCUNHO": "neutral", "EXPIRADO": "neutral"},
    "Contrato": {"VIGENTE": "success", "RASCUNHO": "neutral", "SUSPENSO": "warning", "ENCERRADO": "neutral",
                 "RESCINDIDO": "danger"},
    "Competencia": {"ABERTA": "neutral", "EM_FATURAMENTO": "info", "FATURADA": "warning", "PAGA": "success"},
    "Tarefa": {"A_FAZER": "neutral", "EM_ANDAMENTO": "info", "EM_REVISAO": "warning", "CONCLUIDA": "success",
               "CANCELADA": "neutral"},
    "RelatorioAtividades": {"RASCUNHO": "neutral", "EM_REVISAO": "warning", "APROVADO": "success",
                            "ENVIADO": "info"},
    "Incidente": {"ABERTO": "danger", "FECHADO": "success"},
    "GuiaISS": {"A_DECLARAR": "warning", "DECLARADA": "info", "ENCERRADA": "info", "PAGA": "success"},
    "Venda": {"ABERTA": "info", "EM_PRODUCAO": "warning", "ENTREGUE": "success", "FATURADA": "success",
              "CANCELADA": "neutral"},
    "Habilitacao": {"APTA": "success", "ATENCAO": "warning", "INAPTA": "danger"},
    "TentativaTransmissao": {"AUTORIZADA": "success", "REJEITADA": "danger", "ERRO_COMUNICACAO": "warning",
                             "INCONCLUSIVA": "warning", "EM_ANDAMENTO": "info"},
    "PlanilhaCusto": {"RASCUNHO": "neutral", "VIGENTE": "success", "ARQUIVADA": "neutral"},
}

GENERICO = {
    "ATIVO": "success", "INATIVO": "neutral", "OK": "success", "ERRO": "danger", "PENDENTE": "warning",
}


def cor_status(entidade: str | None, valor: str) -> str:
    if valor.lower() in ("success", "info", "warning", "danger", "neutral"):
        return valor.lower()
    if entidade and entidade in MAPAS:
        return MAPAS[entidade].get(valor, "neutral")
    for mapa in MAPAS.values():
        if valor in mapa:
            return mapa[valor]
    return GENERICO.get(valor, "neutral")
