"""Mensagens recebidas: comandos dos administradores e descadastro (SAIR) de clientes."""

import re
import unicodedata
from datetime import timedelta
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
        c, resultado = confirmacoes.responder(empresa, m.group(2), aceitar, por="WhatsApp do administrador")
        return [("✅ " if c and aceitar else "ℹ️ ") + resultado], []
    m = re.match(r"^nota\s+(\d+)$", texto)
    if m:
        return cmd_nota(empresa, m.group(1))
    comando = texto.split(" ")[0] if texto else ""
    if comando not in ("ajuda", "menu", "?", "pausar", "retomar") and pergunta_original is not None:
        from . import assistente

        resposta = assistente.responder(empresa, telefone, pergunta_original)
        if resposta is not None:
            return resposta
    tabela = {"status": cmd_status, "sistemas": cmd_status, "financeiro": cmd_financeiro, "resumo": cmd_financeiro,
              "previsao": cmd_previsao, "recebimentos": cmd_previsao, "vencidos": cmd_vencidos,
              "faturamento": cmd_faturamento, "notas": cmd_notas, "relatorio": cmd_relatorio, "planilha": cmd_relatorio,
              "pausar": cmd_pausar, "retomar": cmd_retomar}
    if comando in tabela:
        return tabela[comando](empresa)
    return [AJUDA if comando in ("ajuda", "menu", "oi", "ola", "help", "?", "") else
            "Não entendi. Envie *ajuda* para ver os comandos."], []


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
