"""Assistente do administrador no WhatsApp, com Gemini e ferramentas (function calling) sobre os módulos.

Consultas respondem na hora. Ações que gravam dados (despesa, emissão de nota) só criam um pedido de confirmação:
o administrador responde SIM + código para executar. A IA nunca transmite nota nem grava sozinha.
"""

import logging
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.services.integracao import registrar_log
from apps.core.templatetags.ks import brl

from ..models import MensagemWhatsApp
from . import comandos, confirmacoes
from .fila import config_de, mesmo_numero

log = logging.getLogger(__name__)
HISTORICO = 10

INSTRUCOES = """Você é o assistente interno do KS CENTRAL, sistema de gestão da KS TEC Soluções de Tecnologia
(Valença/BA), falando pelo WhatsApp com o dono da empresa. Hoje é {hoje}.
Regras:
- Responda em português do Brasil, curto e direto, formatado para WhatsApp (*negrito*, listas com •). Sem tabelas.
- Use SEMPRE as ferramentas para obter dados; nunca invente números, notas, datas ou status.
- Para registrar despesa ou pedir emissão de nota, chame a ferramenta correspondente: ela cria um pedido e devolve um
  código. Informe o código e diga que a ação só acontece após responder SIM + código.
- Valores em reais no formato R$ 1.234,56. Datas no formato dd/mm/aaaa.
- Se faltar informação para uma ação (valor, contrato, competência), pergunte antes de chamar a ferramenta.
- Se a pergunta não tiver relação com a empresa, responda brevemente que você atende assuntos do KS CENTRAL."""


def disponivel(config):
    return bool(config.ativo and config.assistente_ia and config.gemini_chave_id)


def _data(texto):
    texto = (texto or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ValidationError(f"Data inválida: {texto}. Use dd/mm/aaaa.")


def _competencia(texto):
    texto = (texto or "").strip()
    for fmt in ("%m/%Y", "%Y-%m", "%m/%y"):
        try:
            return datetime.strptime(texto, fmt).date().replace(day=1)
        except ValueError:
            continue
    raise ValidationError(f"Competência inválida: {texto}. Use mm/aaaa.")


def ferramentas(empresa, anexos):
    """Funções expostas ao modelo. Docstrings e tipos viram a descrição das ferramentas."""
    from apps.contratos.models import Contrato

    def _contrato(ref):
        ref = (ref or "").strip()
        qs = Contrato.objects.filter(empresa=empresa).select_related("cliente")
        return (qs.filter(numero__iexact=ref).first() or qs.filter(numero__icontains=ref).first()
                or qs.filter(cliente__razao_social__icontains=ref).first()
                or qs.filter(cliente__nome_fantasia__icontains=ref).first() or qs.filter(objeto__icontains=ref).first())

    def status_monitoramento() -> str:
        """Situação atual de todos os sistemas monitorados (no ar, fora, lento), tempo de resposta e uptime de 30 dias."""
        return comandos.cmd_status(empresa)[0][0]

    def resumo_financeiro() -> str:
        """Resumo financeiro do mês: previsto, recebido, a receber, próximos 7 dias e atrasos."""
        return comandos.cmd_financeiro(empresa)[0][0]

    def previsao_recebimentos(dias: int = 30) -> str:
        """Recebimentos previstos dia a dia nos próximos `dias` dias (receitas lançadas, notas e contratos)."""
        from apps.faturamento.services import previsao

        hoje = timezone.localdate()
        itens = [i for i in previsao.itens_periodo(empresa, hoje, hoje + timedelta(days=max(1, min(dias, 120))))
                 if not i.excluido and i.origem != "RECEBIDO"]
        if not itens:
            return "Nenhum recebimento previsto no período."
        total = sum((i.valor for i in itens), Decimal("0"))
        linhas = [f"{i.data:%d/%m} · {i.titulo} · {brl(i.valor)} ({i.rotulo_origem})" for i in itens[:40]]
        return f"Total previsto: {brl(total)}\n" + "\n".join(linhas)

    def cobrancas_vencidas() -> str:
        """Receitas vencidas e não pagas, com cliente, vencimento e valor."""
        return comandos.cmd_vencidos(empresa)[0][0]

    def listar_contratos() -> str:
        """Contratos com cliente, valor mensal, vigência, saldo e próxima emissão programada."""
        from apps.faturamento.services import ciclos

        linhas = []
        for c in Contrato.objects.filter(empresa=empresa).select_related("cliente").order_by("numero"):
            agenda = getattr(c, "agenda_faturamento", None)
            prox = ciclos.proxima_execucao(agenda) if agenda and agenda.ativo else None
            linhas.append(f"{c.numero} · {c.cliente} · {brl(c.valor_mensal or 0)}/mês · {c.get_status_display()} · "
                          f"vigência até {c.vigencia_fim_atual:%d/%m/%Y} · saldo {brl(c.saldo)}"
                          + (f" · próxima emissão {prox.emissao:%d/%m/%Y}" if prox else ""))
        return "\n".join(linhas) or "Nenhum contrato cadastrado."

    def faturamento_pendente() -> str:
        """Competências ainda não faturadas por contrato, emissões programadas e bloqueios do faturamento recorrente."""
        from apps.faturamento.models import CicloFaturamento as C

        hoje = timezone.localdate()
        pend = C.objects.filter(empresa=empresa, data_emissao__lte=hoje + timedelta(days=30)).exclude(
            status__in=["AUTORIZADO", "PULADO"]).select_related("agenda__contrato").order_by("agenda__contrato__numero", "competencia")
        if not pend:
            return "Nenhuma competência pendente."
        return "\n".join(f"{c.agenda.contrato.numero} · competência {c.competencia:%m/%Y} · {brl(c.valor)} · "
                         f"{c.get_status_display()} · emissão {c.data_emissao:%d/%m/%Y}"
                         + (f" · {c.mensagem[:90]}" if c.mensagem else "") for c in pend)

    def consultar_nota(numero: str) -> str:
        """Dados de uma NFS-e pelo número (ou final do número). Envia também o PDF e o XML pelo WhatsApp."""
        textos, arquivos = comandos.cmd_nota(empresa, "".join(ch for ch in numero if ch.isdigit()) or numero)
        anexos.extend(arquivos)
        from apps.fiscal.models import NotaFiscal

        nota = NotaFiscal.objects.filter(empresa=empresa, numero_nfse__endswith=numero.strip()).first()
        if nota:
            return (f"{textos[0]}\nCompetência {nota.competencia:%m/%Y} · líquido {brl(nota.valor_liquido)} · "
                    f"ISS {brl(nota.valor_iss)}{' retido' if nota.iss_retido else ''} · {nota.get_status_display()}"
                    + (f" · contrato {nota.contrato.numero}" if nota.contrato_id else ""))
        return textos[0]

    def listar_notas(contrato: str = "", limite: int = 10) -> str:
        """Últimas NFS-e emitidas, opcionalmente de um contrato (número ou nome do cliente)."""
        from apps.fiscal.models import NotaFiscal

        qs = NotaFiscal.objects.filter(empresa=empresa).exclude(status="RASCUNHO").select_related("tomador", "contrato")
        if contrato:
            c = _contrato(contrato)
            if c is None:
                return f"Contrato '{contrato}' não encontrado."
            qs = qs.filter(contrato=c)
        notas = qs.order_by("-autorizada_em")[:max(1, min(limite, 30))]
        return "\n".join(f"nº {n.numero_nfse} · {n.tomador} · {brl(n.valor_servicos)} · {n.get_status_display()}"
                         + (f" · {n.autorizada_em:%d/%m/%Y}" if n.autorizada_em else "") for n in notas) or "Nenhuma nota."

    def solicitar_nota(contrato: str, competencia: str) -> str:
        """Pede a emissão da NFS-e de um contrato numa competência (mm/aaaa). Não emite: cria um pedido de confirmação."""
        from apps.faturamento.models import CicloFaturamento
        from apps.faturamento.services import ciclos

        c = _contrato(contrato)
        if c is None:
            return f"Contrato '{contrato}' não encontrado."
        agenda = getattr(c, "agenda_faturamento", None)
        if agenda is None:
            return f"O contrato {c.numero} não tem faturamento recorrente configurado."
        comp = _competencia(competencia)
        ciclos.planejar(agenda, hoje=timezone.localdate() + timedelta(days=62))
        ciclo = CicloFaturamento.objects.filter(agenda=agenda, competencia=comp).first()
        if ciclo is None:
            return f"Competência {comp:%m/%Y} fora da agenda do contrato {c.numero}."
        if ciclo.status in ("AUTORIZADO", "TRANSMITIDO"):
            return f"A competência {comp:%m/%Y} do contrato {c.numero} já foi {ciclo.get_status_display().lower()}."
        pedido = confirmacoes.criar(empresa, "faturamento.emitir", ciclo,
                                    f"Emitir NFS-e {c.numero} {comp:%m/%Y} · {brl(ciclo.valor)}", horas=24)
        return (f"Pedido criado: NFS-e do contrato {c.numero} ({c.cliente}), competência {comp:%m/%Y}, "
                f"valor {brl(ciclo.valor)}. Código {pedido.codigo}: responda SIM {pedido.codigo} para gerar e transmitir.")

    def registrar_despesa(descricao: str, valor: float, vencimento: str, centro_ou_contrato: str = "Administrativo",
                          categoria: str = "", ja_pago: bool = False) -> str:
        """Registra uma despesa (custo). `centro_ou_contrato`: nome do centro de custo (ex.: Administrativo, para custos
        globais da empresa) ou número/cliente do contrato. `vencimento` em dd/mm/aaaa. Cria um pedido de confirmação."""
        from apps.financeiro.models import CategoriaFinanceira, CentroCusto

        try:
            valor_dec = Decimal(str(round(float(valor), 2)))
        except (InvalidOperation, ValueError, TypeError):
            return "Valor inválido."
        if valor_dec <= 0:
            return "O valor deve ser maior que zero."
        venc = _data(vencimento)
        centro = CentroCusto.objects.filter(empresa=empresa, ativo=True, nome__icontains=centro_ou_contrato).first()
        if centro is None:
            c = _contrato(centro_ou_contrato)
            centro = getattr(c, "centro_custo", None) if c else None
        if centro is None:
            return f"Centro de custo ou contrato '{centro_ou_contrato}' não encontrado."
        cats = CategoriaFinanceira.objects.filter(empresa=empresa, tipo="DESPESA", ativo=True)
        cat = (cats.filter(nome__icontains=categoria).first() if categoria else None) or cats.filter(nome="Administrativas").first() or cats.first()
        if cat is None:
            return "Cadastre uma categoria de despesa no financeiro."
        dados = {"descricao": descricao[:300], "valor": str(valor_dec), "vencimento": venc.isoformat(),
                 "centro": str(centro.pk), "categoria": str(cat.pk), "pago": bool(ja_pago)}
        pedido = confirmacoes.criar(empresa, "financeiro.despesa", centro, f"Despesa {descricao[:80]} · {brl(valor_dec)}",
                                    horas=24, dados=dados)
        return (f"Pedido criado: despesa “{descricao}” de {brl(valor_dec)}, vencimento {venc:%d/%m/%Y}, centro "
                f"{centro.nome}, categoria {cat.nome}{', já paga' if ja_pago else ''}. "
                f"Responda SIM {pedido.codigo} para registrar.")

    def certidoes() -> str:
        """Certidões da empresa: validade e situação (válida, vencendo, vencida)."""
        from apps.certidoes.models import TipoCertidao

        linhas = []
        for t in TipoCertidao.objects.filter(empresa=empresa, ativo=True):
            ultima = t.ultima
            linhas.append(f"{t.nome}: " + (f"{ultima.get_status_display()} até {ultima.data_validade:%d/%m/%Y}"
                                            if ultima else "sem certidão cadastrada"))
        return "\n".join(linhas)

    def custos_do_periodo(meses: int = 1) -> str:
        """Custos e resultado por contrato nos últimos `meses` meses, com rateio dos custos globais."""
        from apps.contratos.models import somar_meses
        from apps.financeiro.services.custos_relatorio import apurar

        hoje = timezone.localdate()
        dados = apurar(empresa, somar_meses(hoje.replace(day=1), -max(0, meses - 1)), hoje)
        linhas = [f"{x['contrato'].numero}: receita {brl(x['receita'])}, custo {brl(x['custo_total'])}, resultado "
                  f"{brl(x['resultado'])}" for x in dados["linhas"]]
        return (f"Custos totais {brl(dados['total_custos'])} (globais {brl(dados['total_global'])}).\n" + "\n".join(linhas))

    def enviar_relatorio_financeiro() -> str:
        """Gera e envia a planilha XLSX com o resumo financeiro (previsão, em aberto, notas do ano)."""
        from . import relatorio

        anexos.append(relatorio.gerar(empresa))
        return "Planilha gerada; será enviada em seguida."

    return [status_monitoramento, resumo_financeiro, previsao_recebimentos, cobrancas_vencidas, listar_contratos,
            faturamento_pendente, consultar_nota, listar_notas, solicitar_nota, registrar_despesa, certidoes,
            custos_do_periodo, enviar_relatorio_financeiro]


def historico(empresa, telefone):
    msgs = MensagemWhatsApp.objects.filter(empresa=empresa, tipo="TEXTO").exclude(texto="").order_by("-criado_em")[:60]
    conversa = [m for m in msgs if mesmo_numero(m.telefone, telefone)][:HISTORICO]
    return list(reversed(conversa))


def responder(empresa, telefone, texto, cliente=None):
    """Retorna (textos, anexos) ou None quando o assistente não está disponível ou falhou."""
    config = config_de(empresa)
    if not disponivel(config):
        return None
    from google import genai
    from google.genai import types

    anexos = []
    conteudos = []
    for m in historico(empresa, telefone)[:-1]:  # a última é a própria pergunta, já registrada
        conteudos.append(types.Content(role="user" if m.direcao == "ENTRADA" else "model",
                                       parts=[types.Part(text=m.texto[:2000])]))
    conteudos.append(types.Content(role="user", parts=[types.Part(text=texto[:2000])]))
    inicio = time.monotonic()
    try:
        cli = cliente or genai.Client(api_key=config.gemini_chave.ler())
        resposta = cli.models.generate_content(
            model=config.modelo_ia or "gemini-flash-latest", contents=conteudos,
            config=types.GenerateContentConfig(
                system_instruction=INSTRUCOES.format(hoje=f"{timezone.localdate():%d/%m/%Y}"),
                tools=ferramentas(empresa, anexos), temperature=0.2,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=6)))
        saida = (resposta.text or "").strip()
    except Exception as erro:  # noqa: BLE001 — sem IA, o bot volta aos comandos fixos.
        registrar_log("GEMINI", "assistente_whatsapp", request={"pergunta": texto[:300]}, response=str(erro)[:500],
                      duracao_ms=int((time.monotonic() - inicio) * 1000), empresa=empresa)
        log.warning("assistente indisponível: %s", erro)
        return None
    registrar_log("GEMINI", "assistente_whatsapp", request={"pergunta": texto[:300]}, response={"resposta": saida[:1000]},
                  duracao_ms=int((time.monotonic() - inicio) * 1000), sucesso=True, empresa=empresa)
    return [saida or "Não consegui responder agora. Envie *ajuda* para ver os comandos."], anexos


# ---------------------------------------------------------------------------
# Execução das ações confirmadas
# ---------------------------------------------------------------------------

@confirmacoes.acao("faturamento.emitir")
def _emitir(c, aceitar, por):
    from apps.faturamento.models import CicloFaturamento
    from apps.faturamento.services import ciclos

    ciclo = CicloFaturamento.objects.filter(pk=c.objeto_id, empresa=c.empresa).first()
    if ciclo is None:
        return "Competência não encontrada."
    if not aceitar:
        return "Ok, nada foi emitido."
    if ciclo.status == "AGUARDANDO":
        ciclo = ciclos.confirmar(ciclo, None, origem=por)
    else:
        ciclo = ciclos.executar(ciclo, None, manual=True)
    return f"{ciclo}: {ciclo.mensagem or ciclo.get_status_display()}"


@confirmacoes.acao("financeiro.despesa")
def _despesa(c, aceitar, por):
    from apps.financeiro.models import CategoriaFinanceira, CentroCusto, ContaBancaria, Lancamento
    from apps.financeiro.services.lancamentos import baixar, salvar

    if not aceitar:
        return "Ok, a despesa não foi registrada."
    d = c.dados
    lanc = Lancamento(empresa=c.empresa, tipo="DESPESA", descricao=d["descricao"], valor=Decimal(d["valor"]),
                      categoria=CategoriaFinanceira.objects.get(pk=d["categoria"], empresa=c.empresa),
                      centro_custo=CentroCusto.objects.get(pk=d["centro"], empresa=c.empresa),
                      conta_bancaria=ContaBancaria.objects.filter(empresa=c.empresa, ativo=True).first(),
                      data_competencia=date.fromisoformat(d["vencimento"]), data_vencimento=date.fromisoformat(d["vencimento"]))
    salvar(lanc)
    texto = f"Despesa registrada: {lanc.descricao} · {brl(lanc.valor)}."
    if d.get("pago"):
        try:
            baixar(lanc, data_pagamento=min(lanc.data_vencimento, timezone.localdate()), forma_pagamento="PIX")
            texto += " Baixa registrada."
        except ValidationError as erro:
            texto += " Baixa pendente: " + "; ".join(erro.messages)
    return texto
