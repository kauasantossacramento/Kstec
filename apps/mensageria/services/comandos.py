"""Mensagens recebidas: comandos dos administradores e descadastro (SAIR) de clientes."""

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.core.services.notificacoes import notificar_papeis
from apps.core.templatetags.ks import brl
from apps.core.validadores import formatar_telefone

from ..models import ContatoWhatsApp, MensagemWhatsApp
from . import confirmacoes
from .fila import config_de, eh_admin, enfileirar, estado_de, mesmo_numero

SAIR = {"sair", "parar", "stop", "cancelar", "descadastrar", "remover"}
AJUDA = """🤖 *KS CENTRAL* — comandos
• *status* — sistemas monitorados
• *financeiro* — resumo do mês
• *previsao* — recebimentos dos próximos 15 dias
• *vencidos* — cobranças em atraso
• *faturamento* — próximas emissões e pendências
• *proximas* — emissões dos próximos 60 dias, por contrato
• *contratos* — contratos vigentes, objeto e próxima emissão
• *receber* — notas em aberto por competência
• *recebido 10/2026* — dar baixa nas notas da competência
• *recebido 136 10/2026* — só as do contrato (número ou nome)
• *entradas* — o que já foi recebido no mês (ou *entradas 09/2026*)
• *documentos 136 10/2026* — nota, recibo, relatório, planilha e SLA da competência (acrescente *certidoes* ou *contrato*)
• *notas* — últimas NFS-e
• *nota 123* — PDF e XML da NFS-e nº 123
• *relatorio* — planilha com o resumo financeiro
• *pausar* / *retomar* — envios a clientes
• *sim 1234* / *nao 1234* — responder confirmações"""


def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"\s+", " ", t)


def registrar_entrada(empresa, telefone, texto, wa_id=""):
    if wa_id and MensagemWhatsApp.objects.filter(empresa=empresa, direcao="ENTRADA", wa_id=wa_id).exists():
        return None
    msg = MensagemWhatsApp(empresa=empresa, direcao="ENTRADA", telefone=telefone, texto=(texto or "")[:4000],
                           status=MensagemWhatsApp.Status.RECEBIDA, wa_id=wa_id[:80], enviada_em=timezone.now())
    msg.contato = next((c for c in ContatoWhatsApp.objects.filter(empresa=empresa, ativo=True)
                        if mesmo_numero(c.telefone, telefone)), None)
    msg.save()
    return msg


def processar(empresa, telefone, texto, wa_id=""):
    """Ponto de entrada do worker. Retorna a lista de mensagens de resposta enfileiradas."""
    entrada = registrar_entrada(empresa, telefone, texto, wa_id)
    if entrada is None:
        return []
    config = config_de(empresa)
    if eh_admin(config, telefone):
        if not config.comandos:
            return []
        textos, anexos = responder_admin(empresa, normalizar(texto), telefone, texto)
        saida = [enfileirar(empresa, telefone, t, para_admin=True) for t in textos]
        saida += [enfileirar(empresa, telefone, "", anexo=a, nome_arquivo=a.nome, para_admin=True, ordem=i)
                  for i, a in enumerate(anexos, 1)]
        return [m for m in saida if m]
    return tratar_cliente(empresa, entrada, normalizar(texto))


def tratar_cliente(empresa, entrada, texto):
    contato = entrada.contato
    if texto in SAIR:
        contatos = [c for c in ContatoWhatsApp.objects.filter(empresa=empresa) if mesmo_numero(c.telefone, entrada.telefone)]
        for c in contatos:
            c.descadastrado_em = timezone.now()
            c.save()
        MensagemWhatsApp.objects.filter(empresa=empresa, telefone=entrada.telefone, direcao="SAIDA",
                                        status__in=["PENDENTE", "RETIDA"]).update(status="CANCELADA")
        resposta = enfileirar(empresa, entrada.telefone, "Pronto, você não receberá mais mensagens automáticas por aqui. "
                              "Se precisar, é só nos chamar. 👍", contato=contatos[0] if contatos else None,
                              chave=f"sair:{entrada.telefone}:{timezone.localdate():%Y%m%d}")
        avisar_admin(empresa, f"🚫 {contato or formatar_telefone(entrada.telefone)} pediu para não receber mensagens.")
        return [resposta] if resposta else []
    # Mensagens livres de clientes não recebem resposta automática: o administrador é avisado.
    origem = f"{contato.nome} ({contato.pessoa})" if contato and contato.pessoa else formatar_telefone(entrada.telefone)
    avisar_admin(empresa, f"📩 Mensagem de {origem}:\n{entrada.texto[:800]}",
                 chave=f"encaminhar:{entrada.pk}")
    notificar_papeis(["Financeiro"], f"WhatsApp de {origem}", entrada.texto[:500], empresa=empresa,
                     link="/whatsapp/mensagens/?direcao=ENTRADA")
    return []


def avisar_admin(empresa, texto, chave=""):
    from .fila import para_admins

    return para_admins(empresa, texto, chave=chave)


# ---------------------------------------------------------------------------
# Comandos do administrador
# ---------------------------------------------------------------------------

def responder_admin(empresa, texto, telefone="", pergunta_original=None):
    m = re.match(r"^(sim|s|nao|n|ok)\s+(\d{4})$", texto)
    if m:
        aceitar = m.group(1) in ("sim", "s", "ok")
        por = "WhatsApp do administrador" + (f" ({telefone})" if telefone else "")
        c, resultado = confirmacoes.responder(empresa, m.group(2), aceitar, por=por)
        return [("✅ " if c and aceitar else "ℹ️ ") + resultado], []
    m = re.match(r"^nota\s+(\d+)$", texto)
    if m:
        return cmd_nota(empresa, m.group(1))
    m = RECEBIDO.match(texto)
    if m:
        return cmd_recebido(empresa, m.group("contrato"), int(m.group("mes")), int(m.group("ano")), m.group("forma"))
    m = ENTRADAS.match(texto)
    if m:
        return cmd_entradas(empresa, int(m.group("mes")) if m.group("mes") else None,
                            int(m.group("ano")) if m.group("ano") else None)
    m = DOCUMENTOS.match(texto)
    if m:
        return cmd_documentos(empresa, m.group("contrato"), int(m.group("mes")), int(m.group("ano")),
                              m.group("tipos").split())
    comando =texto.split(" ")[0] if texto else ""
    if comando not in ("ajuda", "menu", "?", "pausar", "retomar") and pergunta_original is not None:
        from . import assistente

        resposta = assistente.responder(empresa, telefone, pergunta_original)
        if resposta is not None:
            return resposta
    tabela = {"status": cmd_status, "sistemas": cmd_status, "financeiro": cmd_financeiro, "resumo": cmd_financeiro,
              "previsao": cmd_previsao, "recebimentos": cmd_previsao, "vencidos": cmd_vencidos,
              "faturamento": cmd_faturamento, "proximas": cmd_proximas, "emissoes": cmd_proximas,
              "contratos": cmd_contratos, "receber": cmd_receber, "abertos": cmd_receber, "notas": cmd_notas, "relatorio": cmd_relatorio, "planilha": cmd_relatorio,
              "pausar": cmd_pausar, "retomar": cmd_retomar}
    if comando in tabela:
        return tabela[comando](empresa)
    return [AJUDA if comando in ("ajuda", "menu", "oi", "ola", "help", "?", "") else
            "Não entendi. Envie *ajuda* para ver os comandos."], []


RECEBIDO = re.compile(r"^recebid[oa]s?\s+(?:(?P<contrato>\S+)\s+)?(?P<mes>\d{1,2})/(?P<ano>\d{4})"
                      r"(?:\s+(?P<forma>pix|ted|transferencia|boleto|dinheiro))?$")
FORMAS = {"pix": "PIX", "ted": "TED", "transferencia": "TED", "boleto": "BOLETO", "dinheiro": "DINHEIRO"}
ENTRADAS = re.compile(r"^(?:entradas|recebidos)(?:\s+(?P<mes>\d{1,2})/(?P<ano>\d{4}))?$")
DOCUMENTOS = re.compile(r"^(?:documentos|docs)\s+(?P<contrato>\S+)\s+(?P<mes>\d{1,2})/(?P<ano>\d{4})(?P<tipos>(?:\s+\w+)*)$")
TIPOS_DOC = {"nota": "nota", "nfse": "nota", "danfse": "nota", "recibo": "recibo", "relatorio": "relatorio",
             "atividades": "relatorio", "planilha": "planilha", "custos": "planilha", "demonstrativo": "planilha",
             "sla": "sla", "certidoes": "certidoes", "certidao": "certidoes", "contrato": "contrato"}
DOCS_PADRAO = ("nota", "recibo", "relatorio", "planilha", "sla")


def achar_contrato(empresa, ref):
    """Contrato pelo número (exato ou parcial), cliente ou objeto."""
    from apps.contratos.models import Contrato

    ref = (ref or "").strip()
    if not ref:
        return None
    qs = Contrato.objects.filter(empresa=empresa).select_related("cliente")
    return (qs.filter(numero__iexact=ref).first() or qs.filter(numero__icontains=ref).first()
            or qs.filter(cliente__razao_social__icontains=ref).first()
            or qs.filter(cliente__nome_fantasia__icontains=ref).first() or qs.filter(objeto__icontains=ref).first())


def _casa_contrato(ct, termo):
    return bool(ct) and (normalizar(ct.numero).startswith(termo) or termo in normalizar(str(ct.cliente))
                         or termo in normalizar(ct.objeto))


def resumo_objeto(contrato, limite=70):
    texto = re.split(r"\s[—–-]\s|[.;:]", contrato.objeto or "", maxsplit=1)[0].strip()
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


def cmd_proximas(empresa, dias=60):
    from apps.faturamento.models import CicloFaturamento as C

    hoje = timezone.localdate()
    ciclos = C.objects.filter(empresa=empresa, data_emissao__range=(hoje, hoje + timedelta(days=dias))) \
        .exclude(status__in=["PULADO", "AUTORIZADO"]).select_related("agenda__contrato__cliente").order_by("data_emissao")
    if not ciclos:
        return [f"Sem emissões programadas nos próximos {dias} dias."], []
    linhas = [f"• *{c.data_emissao:%d/%m}* · {c.agenda.contrato.numero} — {resumo_objeto(c.agenda.contrato)}\n"
              f"   {c.agenda.contrato.cliente} · comp. {c.competencia:%m/%Y} · {brl(c.valor)}"
              + ("" if c.status == "PROGRAMADO" else f" · _{c.get_status_display().lower()}_") for c in ciclos]
    total = sum((c.valor for c in ciclos), Decimal("0"))
    return [f"📅 *Próximas emissões · {dias} dias*\n" + "\n".join(linhas) + f"\n\nTotal previsto: *{brl(total)}*"], []


def cmd_contratos(empresa):
    from apps.contratos.models import Contrato
    from apps.faturamento.models import CicloFaturamento as C

    hoje = timezone.localdate()
    contratos = Contrato.objects.filter(empresa=empresa, status="VIGENTE").select_related("cliente").order_by("numero")
    if not contratos:
        return ["Nenhum contrato vigente."], []
    linhas = []
    for c in contratos:
        prox = C.objects.filter(agenda__contrato=c, data_emissao__gte=hoje, status__in=["PROGRAMADO", "AGUARDANDO"]) \
            .order_by("data_emissao").first()
        linhas.append(f"• *{c.numero}* — {resumo_objeto(c)}\n   {c.cliente}"
                      + (f" · {brl(c.valor_mensal)}/mês" if c.valor_mensal else "")
                      + f" · vigência até {c.vigencia_fim_atual:%d/%m/%Y}"
                      + (f"\n   próxima emissão {prox.data_emissao:%d/%m/%Y} (comp. {prox.competencia:%m/%Y})" if prox else ""))
    return [f"📑 *Contratos vigentes* ({len(linhas)})\n" + "\n".join(linhas)], []


def _abertos_por_competencia(empresa, ano=None, mes=None, contrato=None):
    from apps.financeiro.services import indicadores

    itens = [x for x in indicadores.abertos(empresa).order_by("data_vencimento")
             if ano is None or indicadores.competencia_de(x) == date(ano, mes, 1)]
    if contrato:
        termo = normalizar(contrato)
        itens = [x for x in itens if _casa_contrato(indicadores.contrato_de(x), termo)]
    return itens


def _linha_recebivel(x):
    from apps.financeiro.services import indicadores

    ct = indicadores.contrato_de(x)
    nota = f"NFS-e {x.nota_fiscal.numero_nfse} · " if x.nota_fiscal_id and x.nota_fiscal.numero_nfse else ""
    return (f"• {ct.numero if ct else (x.pessoa or x.descricao[:30])} · {nota}{brl(x.valor)} · vence {x.data_vencimento:%d/%m}"
            + (" ⚠️" if x.data_vencimento < timezone.localdate() else ""))


def cmd_receber(empresa):
    from apps.financeiro.services import indicadores

    itens = _abertos_por_competencia(empresa)
    if not itens:
        return ["✅ Nenhuma nota em aberto."], []
    grupos = {}
    for x in itens:
        grupos.setdefault(indicadores.competencia_de(x), []).append(x)
    blocos = []
    for comp in sorted(grupos):
        soma = sum((x.valor for x in grupos[comp]), Decimal("0"))
        blocos.append(f"*{comp:%m/%Y}* · {brl(soma)}\n" + "\n".join(_linha_recebivel(x) for x in grupos[comp]))
    total = sum((x.valor for x in itens), Decimal("0"))
    return [f"💰 *A receber* · {brl(total)} ({len(itens)} nota(s))\n\n" + "\n\n".join(blocos)
            + "\n\nPara dar baixa: *recebido 10/2026* (toda a competência) ou *recebido 136 10/2026* (só o contrato). "
              "Peço sua confirmação antes."], []


def cmd_recebido(empresa, contrato, mes, ano, forma=None, data_pagamento=None):
    if not 1 <= mes <= 12:
        return ["Competência inválida. Ex.: *recebido 10/2026*."], []
    hoje = timezone.localdate()
    data_pagamento = data_pagamento or hoje
    if data_pagamento > hoje:
        return [f"A data do recebimento ({data_pagamento:%d/%m/%Y}) não pode ser futura."], []
    itens = _abertos_por_competencia(empresa, ano, mes, contrato)
    if not itens:
        alvo = f" do contrato {contrato}" if contrato else ""
        return [f"Nenhuma nota em aberto{alvo} na competência {mes:02d}/{ano}. Envie *receber* para ver as abertas."], []
    forma = FORMAS.get(forma or "", "TED")
    total = sum((x.valor for x in itens), Decimal("0"))
    c = confirmacoes.criar(empresa, "financeiro.receber", itens[0], f"Baixa de {len(itens)} recebível(is) da competência "
                           f"{mes:02d}/{ano} · {brl(total)}", horas=24,
                           dados={"ids": [str(x.pk) for x in itens], "forma": forma, "data": data_pagamento.isoformat()})
    return [f"💰 *Confirmar recebimento* · competência {mes:02d}/{ano}\n" + "\n".join(_linha_recebivel(x) for x in itens)
            + f"\n\nTotal: *{brl(total)}* · recebido em {data_pagamento:%d/%m/%Y} · {FORMAS_ROTULO.get(forma, forma)}"
            + f"\n\nResponda *SIM {c.codigo}* para dar baixa ou *NAO {c.codigo}* para cancelar."
            + "\n_Outra forma: acrescente pix, ted, boleto ou dinheiro ao comando (ex.: recebido 10/2026 pix)._"], []


FORMAS_ROTULO = {"PIX": "PIX", "TED": "transferência", "BOLETO": "boleto", "DINHEIRO": "dinheiro"}


def resumo_recebidos(empresa, inicio, fim, contrato=None):
    """Receitas baixadas (data de pagamento) no período, agrupadas por contrato."""
    from apps.financeiro.models import Lancamento
    from apps.financeiro.services import indicadores

    qs = Lancamento.objects.filter(empresa=empresa, tipo="RECEITA", status="PAGO", data_pagamento__range=(inicio, fim)) \
        .select_related("nota_fiscal__contrato__cliente", "pessoa", "centro_custo__contrato").order_by("data_pagamento")
    itens = list(qs)
    if contrato:
        termo = normalizar(contrato)
        itens = [x for x in itens if _casa_contrato(indicadores.contrato_de(x), termo)]
    periodo = f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"
    if not itens:
        return f"Nenhum recebimento registrado de {periodo}" + (f" para {contrato}." if contrato else ".")
    grupos = {}
    for x in itens:
        ct = indicadores.contrato_de(x)
        grupos.setdefault(f"{ct.numero} — {ct.cliente}" if ct else str(x.pessoa or "Sem contrato"), []).append(x)
    blocos = []
    for nome, lista in sorted(grupos.items(), key=lambda g: -sum(x.valor_pago or x.valor for x in g[1])):
        soma = sum((x.valor_pago or x.valor for x in lista), Decimal("0"))
        blocos.append(f"*{nome}* · {brl(soma)}\n" + "\n".join(
            f"• {x.data_pagamento:%d/%m} · " + (f"NFS-e {x.nota_fiscal.numero_nfse} · " if x.nota_fiscal_id else "")
            + f"comp. {indicadores.competencia_de(x):%m/%Y} · {brl(x.valor_pago or x.valor)}"
            + (f" · {x.get_forma_pagamento_display()}" if x.forma_pagamento else "") for x in lista))
    total = sum((x.valor_pago or x.valor for x in itens), Decimal("0"))
    return f"✅ *Recebido de {periodo}* · {brl(total)} ({len(itens)})\n\n" + "\n\n".join(blocos)


def cmd_entradas(empresa, mes=None, ano=None):
    from apps.financeiro.services import indicadores

    hoje = timezone.localdate()
    if mes is not None and not 1 <= mes <= 12:
        return ["Mês inválido. Ex.: *entradas 09/2026*."], []
    inicio = date(ano, mes, 1) if mes else hoje.replace(day=1)
    return [resumo_recebidos(empresa, inicio, min(indicadores.fim_mes(inicio), hoje) if inicio <= hoje
                             else indicadores.fim_mes(inicio))], []


def _documento_competencia(contrato, competencia, chave):
    """(anexo, descrição) do relatório, planilha ou SLA: aprovado e assinado, enviado em Documentos ou prévia do
    rascunho. Sem documento: (None, motivo)."""
    from apps.contratos.models import DocumentoContrato
    from apps.core.models import Anexo
    from apps.financeiro.models import PlanilhaCustos
    from apps.fiscal.services import envio_documentos
    from apps.operacao.models import RelatorioAtividades
    from apps.sla.models import RelatorioSLA

    modelo, tipo, nome, arquivo = {
        "relatorio": (RelatorioAtividades, "RELATORIO_ATIVIDADES", "relatório de atividades", "relatorio_atividades"),
        "planilha": (PlanilhaCustos, "PLANILHA_CUSTOS", "planilha de custos", "demonstrativo_custos"),
        "sla": (RelatorioSLA, "RELATORIO_SLA", "relatório de SLA", "relatorio_sla")}[chave]
    base = modelo.objects.filter(empresa=contrato.empresa, contrato=contrato, competencia=competencia,
                                 ativo=True).order_by("-versao")
    aprovado = base.filter(status="APROVADO", pdf__isnull=False).select_related("pdf").first()
    if aprovado:
        return aprovado.pdf, f"{nome} (assinado)"
    enviado = DocumentoContrato.objects.filter(contrato=contrato, competencia=competencia, tipo=tipo, ativo=True) \
        .select_related("anexo").first()
    if enviado:
        return enviado.anexo, f"{nome} (documento enviado)"
    rascunho = base.filter(status="RASCUNHO").first()
    if rascunho is None:
        return None, f"{nome}: não há"
    try:
        pdf = envio_documentos.pdf_previa(chave, rascunho)
    except Exception as erro:  # noqa: BLE001 — rascunho incompleto não impede os demais documentos.
        return None, f"{nome}: prévia indisponível ({erro})"
    return (Anexo.criar(contrato, f"PREVIA_{arquivo}_{competencia:%Y%m}.pdf", pdf, retencao_anos=1,
                        descricao="Prévia enviada pelo WhatsApp"), f"{nome} (PRÉVIA, ainda não aprovado)")


def cmd_documentos(empresa, ref, mes, ano, tipos=None):
    """PDFs de uma competência do contrato para o administrador: nota, recibo, relatório, planilha, SLA,
    e, se pedidos, certidões vigentes e documentos do contrato."""
    from django.contrib.contenttypes.models import ContentType
    from django.core.exceptions import ValidationError

    from apps.contratos.models import DocumentoContrato
    from apps.core.models import Anexo
    from apps.fiscal.models import NotaFiscal
    from apps.fiscal.services import envio_documentos, recibo
    from apps.fiscal.services.entregas import certidoes_validas
    from apps.fiscal.services.pdf_nfse import garantir_pdf

    if not 1 <= mes <= 12:
        return ["Competência inválida. Ex.: *documentos 136 10/2026*."], []
    contrato = achar_contrato(empresa, ref)
    if contrato is None:
        return [f"Contrato '{ref}' não encontrado. Envie *contratos* para ver a lista."], []
    pedidos = [TIPOS_DOC[t] for t in (normalizar(t) for t in tipos or []) if t in TIPOS_DOC]
    explicitos = bool(pedidos)
    pedidos = list(dict.fromkeys(pedidos or DOCS_PADRAO))
    competencia = date(ano, mes, 1)
    nota = NotaFiscal.objects.filter(empresa=empresa, contrato=contrato, competencia__year=ano, competencia__month=mes,
                                     status="AUTORIZADA").order_by("-autorizada_em").first()
    anexos, enviados, faltas = [], [], []
    for chave in pedidos:
        try:
            if chave in ("nota", "recibo"):
                if nota is None:
                    faltas.append(f"{'NFS-e' if chave == 'nota' else 'recibo'}: sem nota autorizada na competência")
                    continue
                if chave == "nota":
                    anexos.append(garantir_pdf(nota))
                    enviados.append(f"NFS-e {nota.numero_nfse}")
                else:
                    anexos.append(Anexo.objects.filter(
                        content_type=ContentType.objects.get_for_model(nota), object_id=str(nota.pk),
                        nome=f"recibo_nfse_{nota.numero_nfse}.pdf").order_by("-criado_em").first() or recibo.gerar(nota))
                    enviados.append("recibo")
            elif chave in ("relatorio", "planilha", "sla"):
                if chave == "sla" and not explicitos and not contrato.exige_relatorio_sla:
                    continue
                if chave == "relatorio" and not explicitos and not contrato.exige_relatorio_atividades:
                    continue
                anexo, descricao = _documento_competencia(contrato, competencia, chave)
                if anexo is None:
                    faltas.append(descricao)
                    continue
                anexos.append(anexo)
                enviados.append(descricao)
            elif chave == "certidoes":
                certs = certidoes_validas(contrato)
                anexos += envio_documentos.copias_certidoes(contrato, certs, "Cópia enviada pelo WhatsApp")
                enviados.append(f"{len(certs)} certidão(ões) vigente(s)")
            elif chave == "contrato":
                docs = list(DocumentoContrato.objects.filter(contrato=contrato, tipo="CONTRATO", ativo=True)
                            .select_related("anexo").order_by("-criado_em")[:5])
                if not docs:
                    faltas.append("contrato: nenhum arquivo em Contrato → Documentos")
                    continue
                anexos += [d.anexo for d in docs]
                enviados.append(f"{len(docs)} documento(s) do contrato")
        except ValidationError as erro:
            faltas.append("; ".join(erro.messages))
    texto = f"📎 *Documentos · {contrato.numero} · {competencia:%m/%Y}*\n{contrato.cliente}"
    if enviados:
        texto += "\nSeguem: " + ", ".join(enviados) + "."
    if faltas:
        texto += "\n⚠️ " + "\n⚠️ ".join(faltas)
    if not anexos:
        texto += "\nNenhum arquivo para enviar."
    return [texto], anexos


def cmd_status(empresa):
    from apps.sla.models import Sistema

    sistemas = list(Sistema.objects.filter(empresa=empresa, ativo=True).order_by("nome"))
    if not sistemas:
        return ["Nenhum sistema monitorado cadastrado."], []
    icones = {"OPERACIONAL": "🟢", "DEGRADADO": "🟡", "FORA": "🔴", "MANUTENCAO": "🔧", "DESCONHECIDO": "⚪"}
    linhas = [f"{icones.get(s.status, '⚪')} *{s.nome}* — {s.get_status_display()}"
              + (f" · {s.ultimo_tempo_ms} ms" if s.ultimo_tempo_ms else "")
              + (f" · uptime 30d {s.uptime_30d:.2f}%" if s.uptime_30d is not None else "") for s in sistemas]
    fora = sum(1 for s in sistemas if s.status == "FORA")
    cab = "Todos os sistemas operando." if not fora else f"⚠️ {fora} sistema(s) fora do ar."
    return [f"📡 *Monitoramento*\n{cab}\n\n" + "\n".join(linhas)], []


def cmd_financeiro(empresa):
    from apps.faturamento.services import previsao

    hoje = timezone.localdate()
    d = previsao.mes(empresa, hoje)
    semana = [i for i in previsao.itens_periodo(empresa, hoje, hoje + timedelta(days=7)) if not i.excluido and i.origem != "RECEBIDO"]
    total_semana = sum((i.valor for i in semana), Decimal("0"))
    texto = (f"💼 *Financeiro · {hoje:%m/%Y}*\n"
             f"Previsto no mês: {brl(d['total'])}\n"
             f"Recebido: {brl(d['totais']['RECEBIDO'])}\n"
             f"A receber: {brl(d['a_receber'])}\n"
             f"Próximos 7 dias: {brl(total_semana)} ({len(semana)} item(ns))\n"
             f"Em atraso (meses anteriores): {brl(d['valor_atrasados_anteriores'])} · {d['atrasados_anteriores']} lanç.\n\n"
             "Envie *previsao* para o detalhe por dia ou *relatorio* para a planilha.")
    return [texto], []


def cmd_previsao(empresa):
    from apps.faturamento.services import previsao

    hoje = timezone.localdate()
    itens = previsao.itens_periodo(empresa, hoje, hoje + timedelta(days=15))
    dias = previsao.agenda_dias_semana([i for i in itens if i.origem != "RECEBIDO"])
    if not dias:
        return ["Nenhum recebimento previsto nos próximos 15 dias."], []
    linhas = [f"{d:%d/%m} ({['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'][d.weekday()]}): {brl(v)}" for d, v in dias]
    total = sum((v for _, v in dias), Decimal("0"))
    return ["📅 *Recebimentos · 15 dias*\n" + "\n".join(linhas) + f"\n\nTotal: *{brl(total)}*"], []


def cmd_vencidos(empresa):
    from apps.financeiro.models import Lancamento

    qs = Lancamento.objects.filter(empresa=empresa, tipo="RECEITA", status__in=["PREVISTO", "PENDENTE", "ATRASADO"],
                                   data_vencimento__lt=timezone.localdate()).select_related("pessoa").order_by("data_vencimento")
    if not qs.exists():
        return ["✅ Nenhuma cobrança vencida."], []
    total = qs.aggregate(v=Sum("valor"))["v"]
    linhas = [f"• {x.data_vencimento:%d/%m} · {x.pessoa or x.descricao} · {brl(x.valor)}" for x in qs[:15]]
    return [f"⏰ *Vencidos* ({qs.count()}) · {brl(total)}\n" + "\n".join(linhas)], []


def cmd_faturamento(empresa):
    from apps.faturamento.models import CicloFaturamento as C
    from apps.mensageria.models import Confirmacao

    hoje = timezone.localdate()
    proximos = C.objects.filter(empresa=empresa, data_emissao__range=(hoje, hoje + timedelta(days=30)),
                                status__in=["PROGRAMADO", "AGUARDANDO"]).select_related("agenda__contrato")[:10]
    pend = C.objects.filter(empresa=empresa, status__in=["AGUARDANDO", "BLOQUEADO", "FALHA"]).select_related("agenda__contrato")
    linhas = [f"• {c.data_emissao:%d/%m} · {c.agenda.contrato.numero} · {brl(c.valor)}" for c in proximos]
    texto = "🧾 *Faturamento recorrente*\n" + ("\n".join(linhas) if linhas else "Sem emissões nos próximos 30 dias.")
    if pend:
        texto += "\n\n*Pendências*"
        for c in pend:
            codigo = Confirmacao.objects.filter(empresa=empresa, acao="faturamento.transmitir", objeto_id=str(c.pk),
                                                status="PENDENTE").values_list("codigo", flat=True).first()
            texto += f"\n• {c.agenda.contrato.numero} {c.competencia:%m/%Y}: {c.get_status_display()}"
            texto += f" — responda SIM {codigo}" if codigo else (f" — {c.mensagem[:80]}" if c.mensagem else "")
    return [texto], []


def cmd_notas(empresa):
    from apps.fiscal.models import NotaFiscal

    notas = NotaFiscal.objects.filter(empresa=empresa).exclude(status="RASCUNHO").select_related("tomador")[:6]
    if not notas:
        return ["Nenhuma NFS-e transmitida ainda."], []
    linhas = [f"• nº {n.numero_nfse or '—'} · {n.tomador} · {brl(n.valor_servicos)} · {n.get_status_display()}" for n in notas]
    return ["🧾 *Últimas NFS-e*\n" + "\n".join(linhas) + "\n\nEnvie *nota <número>* para receber PDF e XML."], []


def cmd_nota(empresa, numero):
    from apps.fiscal.models import NotaFiscal
    from apps.fiscal.services.pdf_nfse import garantir_pdf

    nota = NotaFiscal.objects.filter(empresa=empresa, numero_nfse__endswith=numero, status="AUTORIZADA").first()
    if nota is None:
        return [f"Não encontrei NFS-e autorizada com número terminando em {numero}."], []
    anexos = []
    try:
        anexos.append(garantir_pdf(nota))
    except Exception:  # noqa: BLE001
        pass
    if nota.xml_autorizado_id:
        anexos.append(nota.xml_autorizado)
    return [f"🧾 NFS-e nº {nota.numero_nfse} · {nota.tomador} · {brl(nota.valor_servicos)}"], anexos


def cmd_relatorio(empresa):
    from . import relatorio

    return ["📊 Segue a planilha com o resumo financeiro."], [relatorio.gerar(empresa)]


def cmd_pausar(empresa):
    estado = estado_de(empresa)
    estado.pausado_ate = timezone.now() + timedelta(hours=24)
    estado.motivo_pausa = "pausado pelo administrador"
    estado.save()
    return ["⏸️ Envios a clientes pausados por 24 h. Alertas para você continuam. Envie *retomar* para liberar."], []


def cmd_retomar(empresa):
    estado = estado_de(empresa)
    estado.pausado_ate = None
    estado.motivo_pausa = ""
    estado.falhas_seguidas = 0
    estado.save()
    return ["▶️ Envios a clientes retomados."], []
