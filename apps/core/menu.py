"""Itens da sidebar e do botão '+ Novo'. Itens cuja rota ainda não existe são ocultados."""

from django.urls import NoReverseMatch, reverse

MENU = [
    {"rotulo": "Painel", "url": "painel:home", "icone": "home", "prefixo": "/"},
    {"rotulo": "Contratos", "url": "contratos:contrato_lista", "icone": "file-text", "prefixo": "/contratos/"},
    {"rotulo": "Cadastros", "url": "cadastros:pessoa_lista", "icone": "users", "prefixo": "/cadastros/"},
    {"rotulo": "Fiscal", "url": "fiscal:nota_lista", "icone": "receipt", "prefixo": "/fiscal/"},
    {"rotulo": "Faturamento", "url": "faturamento:home", "icone": "repeat", "prefixo": "/faturamento/",
     "papeis": ["Fiscal", "Financeiro", "Leitura"]},
    {"rotulo": "Financeiro", "url": "financeiro:home", "icone": "wallet", "prefixo": "/financeiro/", "papeis": ["Financeiro", "Fiscal", "Leitura"]},
    {"rotulo": "WhatsApp", "url": "whatsapp:home", "icone": "message", "prefixo": "/whatsapp/",
     "papeis": ["Fiscal", "Financeiro", "Leitura"]},
    {"rotulo": "Comercial", "url": "comercial:orcamento_lista", "icone": "briefcase", "prefixo": "/comercial/"},
    {"rotulo": "Catálogo", "url": "catalogo:item_lista", "icone": "package", "prefixo": "/catalogo/"},
    {"rotulo": "Operação", "url": "operacao:tarefa_lista", "icone": "check-square", "prefixo": "/operacao/"},
    {"rotulo": "Relatórios", "url": "relatorios:home", "icone": "book", "prefixo": "/relatorios/"},
    {"rotulo": "Custos", "url": "custos:planilha_lista", "icone": "calculator", "prefixo": "/custos/"},
    {"rotulo": "Monitoramento", "url": "sla:home", "icone": "activity", "prefixo": "/sla/"},
    {"rotulo": "Certidões", "url": "certidoes:home", "icone": "shield", "prefixo": "/certidoes/"},
    {"rotulo": "Agenda", "url": "painel:agenda", "icone": "calendar", "prefixo": "/agenda/"},
]

MENU_RODAPE = [
    {"rotulo": "Configurações", "url": "core:configuracoes", "icone": "settings", "prefixo": "/configuracoes/"},
]

NOVO = [
    {"rotulo": "Nota fiscal", "url": "fiscal:nota_nova", "papeis": ["Fiscal", "Financeiro"]},
    {"rotulo": "Faturamento recorrente", "url": "faturamento:agenda_nova", "papeis": ["Fiscal", "Financeiro"]},
    {"rotulo": "Orçamento", "url": "comercial:orcamento_novo", "papeis": None},
    {"rotulo": "Lançamento", "url": "financeiro:lancamento_novo", "papeis": ["Financeiro"]},
    {"rotulo": "Tarefa", "url": "operacao:tarefa_nova", "papeis": ["Operação"]},
    {"rotulo": "Certidão", "url": "certidoes:certidao_nova", "papeis": None},
    {"rotulo": "Cliente/fornecedor", "url": "cadastros:pessoa_nova", "papeis": None},
]


def _resolver(itens, path, user=None):
    saida = []
    for item in itens:
        try:
            url = reverse(item["url"])
        except NoReverseMatch:
            continue
        papeis = item.get("papeis")
        if user is not None and papeis and not user.tem_papel("Administrador", *papeis):
            continue
        prefixo = item.get("prefixo")
        ativo = bool(prefixo) and (path == "/" if prefixo == "/" else path.startswith(prefixo))
        saida.append({**item, "href": url, "ativo": ativo})
    return saida


def menu_para(request):
    user = request.user
    return {
        "menu": _resolver(MENU, request.path, user),
        "menu_rodape": _resolver(MENU_RODAPE, request.path),
        "menu_novo": [] if user.somente_leitura else _resolver(NOVO, request.path, user),
    }
