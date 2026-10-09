"""Mensagens a clientes: NFS-e emitida (PDF, XML, link/PIX) e lembretes de vencimento.

Fluxo: monta um LoteEnvio. Se a confirmação for exigida, as mensagens ficam RETIDAS e o administrador recebe
um resumo com destinatários, textos e os mesmos arquivos, respondendo SIM/NAO + código.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.cadastros.models import Pessoa
from apps.core.templatetags.ks import brl
from apps.core.validadores import formatar_telefone
from apps.financeiro.models import Lancamento

from ..models import ContatoWhatsApp, LoteEnvio, MensagemWhatsApp
from . import confirmacoes
from .fila import config_de, enfileirar, para_admins, saudacao, variar

M = MensagemWhatsApp
RODAPE_SAIR = "\n\n_Para não receber mais mensagens por aqui, responda SAIR._"


def perfil(pessoa: Pessoa):
    from apps.cobranca.services.cobrancas import perfil as perfil_cobranca

    return perfil_cobranca(pessoa)


def contatos_aptos(pessoa, finalidade):
    filtro = {"recebe_notas": True} if finalidade == "nota" else {"recebe_cobrancas": True}
    return [c for c in ContatoWhatsApp.objects.filter(pessoa=pessoa, ativo=True, consentimento=True,
                                                      descadastrado_em__isnull=True, **filtro) if c.apto]


def exige_confirmacao(config, perfil_cliente):
    if perfil_cliente.confirmacao == "SEMPRE":
        return True
    if perfil_cliente.confirmacao == "NUNCA":
        return False
    return config.confirmar_envios


def primeiro_nome(contato):
    return (contato.nome or "").split(" ")[0] or "tudo bem"


def cobranca_aberta(lancamento):
    if lancamento is None:
        return None
    return lancamento.cobrancas_asaas.filter(status__in=["PENDING", "OVERDUE"]).order_by("-criado_em").first()


def bloco_pagamento(cobranca):
    if cobranca is None:
        return ""
    partes = []
    if cobranca.link_fatura:
        partes.append(f"🔗 Pagar online: {cobranca.link_fatura}")
    if cobranca.pix_copia_cola:
        partes.append(f"PIX copia e cola:\n{cobranca.pix_copia_cola}")
    return "\n\n" + "\n\n".join(partes) if partes else ""


def texto_nota(contato, nota, lancamento, cobranca, primeira):
    vencimento = f" com vencimento em {lancamento.data_vencimento:%d/%m/%Y}" if lancamento else ""
    abertura = variar(f"{saudacao()}, {primeiro_nome(contato)}!", f"Olá, {primeiro_nome(contato)}! {saudacao()}.")
    corpo = variar(
        f"Segue a NFS-e nº {nota.numero_nfse} da KS TEC, competência {nota.competencia:%m/%Y}, "
        f"no valor de {brl(nota.valor_liquido)}{vencimento}.",
        f"Estamos enviando a nota fiscal de serviço nº {nota.numero_nfse} (competência {nota.competencia:%m/%Y}), "
        f"valor {brl(nota.valor_liquido)}{vencimento}.")
    fecho = variar("Os arquivos PDF e XML vão logo abaixo.", "Seguem abaixo o PDF e o XML da nota.")
    texto = f"{abertura}\n\n{corpo}\n{fecho}{bloco_pagamento(cobranca)}\n\nQualquer dúvida, estamos à disposição."
    return texto + (RODAPE_SAIR if primeira else "")


def texto_lembrete(contato, lancamento, dias, cobranca):
    nome = primeiro_nome(contato)
    valor = brl(lancamento.valor)
    venc = f"{lancamento.data_vencimento:%d/%m/%Y}"
    if dias > 0:
        corpo = variar(f"passando para lembrar que a cobrança de {valor} vence em {venc}.",
                       f"um lembrete rápido: o pagamento de {valor} vence em {venc}.")
    elif dias == 0:
        corpo = variar(f"lembrando que a cobrança de {valor} vence hoje ({venc}).",
                       f"o pagamento de {valor} vence hoje, {venc}.")
    else:
        corpo = variar(f"não identificamos ainda o pagamento de {valor}, vencido em {venc}.",
                       f"consta em aberto o valor de {valor}, com vencimento em {venc}.")
    extra = "" if dias >= 0 else " Se já pagou, por favor desconsidere esta mensagem."
    return f"{saudacao()}, {nome}! Aqui é da KS TEC — {corpo}{extra}{bloco_pagamento(cobranca)}{RODAPE_SAIR}"


def lote_de(confirmacao):
    return LoteEnvio.objects.filter(pk=confirmacao.objeto_id, empresa=confirmacao.empresa).first()


@transaction.atomic
def _montar(empresa, titulo, origem, envios, confirmar, config, nota=None, chave=""):
    """`envios`: lista de (contato, texto, anexos)."""
    lote = LoteEnvio(empresa=empresa, titulo=titulo[:200], origem=origem, nota=nota,
                     status=LoteEnvio.Status.AGUARDANDO if confirmar else LoteEnvio.Status.LIBERADO)
    lote.resumo = "\n".join(f"• {contato.nome} {formatar_telefone(contato.telefone)}" for contato, _, _ in envios)
    lote.save()
    status = M.Status.RETIDA if confirmar else M.Status.PENDENTE
    for contato, texto, anexos in envios:
        enfileirar(empresa, contato.telefone, texto, contato=contato, lote=lote, status=status,
                   chave=f"{chave}:{contato.pk}" if chave else "", ordem=0)
        for i, anexo in enumerate(anexos, 1):
            enfileirar(empresa, contato.telefone, "", anexo=anexo, nome_arquivo=anexo.nome, contato=contato, lote=lote,
                       status=status, chave=f"{chave}:{contato.pk}:{anexo.pk}" if chave else "", ordem=i)
    if confirmar:
        c = confirmacoes.criar(empresa, "mensageria.lote", lote, titulo, horas=config.prazo_confirmacao_h)
        lote.codigo, lote.expira_em = c.codigo, c.expira_em
        lote.save()
        primeiro = envios[0]
        arquivos = ", ".join(a.nome for a in primeiro[2]) or "sem anexos"
        aviso = (f"📤 *Envio aguardando sua confirmação*\n{titulo}\n\nPara:\n{lote.resumo}\n\nArquivos: {arquivos}\n\n"
                 f"Mensagem que será enviada:\n————\n{primeiro[1]}\n————\n\n"
                 f"Responda *SIM {c.codigo}* para enviar ou *NAO {c.codigo}* para cancelar."
                 f"\nPrazo: {timezone.localtime(c.expira_em):%d/%m %H:%M} ({config.get_sem_resposta_display().lower()}).")
        transaction.on_commit(lambda: para_admins(empresa, aviso, primeiro[2], chave=f"lote:{lote.pk}"))
    return lote


def preparar_envio_nota(nota, forcar_confirmacao=None):
    config = config_de(nota.empresa)
    if not config.ativo:
        return None
    p = perfil(nota.tomador)
    if not (p.whatsapp_ativo and p.enviar_nota):
        return None
    contatos = contatos_aptos(nota.tomador, "nota")
    if not contatos:
        return None
    if LoteEnvio.objects.filter(nota=nota, origem="NOTA").exclude(status=LoteEnvio.Status.CANCELADO).exists():
        return LoteEnvio.objects.filter(nota=nota, origem="NOTA").exclude(status=LoteEnvio.Status.CANCELADO).first()
    from apps.fiscal.services.pdf_nfse import garantir_pdf

    anexos = []
    try:
        anexos.append(garantir_pdf(nota))
    except Exception:  # noqa: BLE001 — sem PDF ainda: envia XML e informa no resumo.
        pass
    if nota.xml_autorizado_id:
        anexos.append(nota.xml_autorizado)
    lancamento = Lancamento.objects.filter(nota_fiscal=nota).first()
    cobranca = cobranca_aberta(lancamento) if p.link_pagamento else None
    envios = [(c, texto_nota(c, nota, lancamento, cobranca, c.primeira_mensagem_em is None), anexos) for c in contatos]
    confirmar = exige_confirmacao(config, p) if forcar_confirmacao is None else forcar_confirmacao
    titulo = f"NFS-e {nota.numero_nfse} · {nota.tomador} · {brl(nota.valor_liquido)}"
    return _montar(nota.empresa, titulo, "NOTA", envios, confirmar, config, nota=nota, chave=f"nota:{nota.pk}")


def lembretes(empresa, hoje=None):
    """Lembretes diários de vencimento (antes, no dia e depois), idempotentes por chave."""
    config = config_de(empresa)
    if not (config.ativo and config.lembretes_cobranca):
        return 0
    from apps.cobranca.models import PerfilCobranca, dias

    hoje = hoje or timezone.localdate()
    total = 0
    perfis = PerfilCobranca.objects.filter(empresa=empresa, whatsapp_ativo=True, enviar_lembretes=True,
                                           pessoa__ativo=True).select_related("pessoa")
    for p in perfis:
        contatos = contatos_aptos(p.pessoa, "cobranca")
        if not contatos:
            continue
        janela = [(d, hoje + timedelta(days=d)) for d in dias(p.dias_antes)]
        janela += [(-d, hoje - timedelta(days=d)) for d in dias(p.dias_depois) if d > 0]
        for offset, vencimento in janela:
            abertos = Lancamento.objects.filter(empresa=empresa, pessoa=p.pessoa, tipo="RECEITA",
                                                status__in=["PREVISTO", "PENDENTE", "ATRASADO"],
                                                data_vencimento=vencimento)
            for lanc in abertos:
                chave = f"lembrete:{lanc.pk}:{offset}"
                if MensagemWhatsApp.objects.filter(empresa=empresa, chave__startswith=f"{chave}:").exists():
                    continue
                cobranca = cobranca_aberta(lanc) if p.link_pagamento else None
                envios = [(c, texto_lembrete(c, lanc, offset, cobranca), []) for c in contatos]
                rotulo = "vence hoje" if offset == 0 else f"vence em {offset} dia(s)" if offset > 0 else f"vencido há {-offset} dia(s)"
                _montar(empresa, f"Lembrete · {p.pessoa} · {brl(lanc.valor)} · {rotulo}", "LEMBRETE", envios,
                        exige_confirmacao(config, p), config, chave=chave)
                total += 1
    return total


@transaction.atomic
def liberar(lote, por=""):
    lote = LoteEnvio.objects.select_for_update().get(pk=lote.pk)
    if lote.status not in (LoteEnvio.Status.AGUARDANDO, LoteEnvio.Status.EXPIRADO):
        return lote
    lote.status = LoteEnvio.Status.LIBERADO
    lote.decidido_em, lote.decidido_por = timezone.now(), por[:120]
    lote.save()
    lote.mensagens.filter(status=M.Status.RETIDA).update(status=M.Status.PENDENTE, agendada_para=timezone.now())
    confirmacoes.cancelar_pendentes(lote.empresa, "mensageria.lote", lote.pk, por or "liberado")
    return lote


@transaction.atomic
def cancelar(lote, por="", expirado=False):
    lote = LoteEnvio.objects.select_for_update().get(pk=lote.pk)
    if lote.status in (LoteEnvio.Status.CONCLUIDO, LoteEnvio.Status.CANCELADO):
        return lote
    lote.status = LoteEnvio.Status.EXPIRADO if expirado else LoteEnvio.Status.CANCELADO
    lote.decidido_em, lote.decidido_por = timezone.now(), por[:120]
    lote.save()
    lote.mensagens.filter(status__in=[M.Status.RETIDA, M.Status.PENDENTE]).update(status=M.Status.CANCELADA)
    confirmacoes.cancelar_pendentes(lote.empresa, "mensageria.lote", lote.pk, por or "cancelado")
    return lote


def concluir_se_terminou(lote_id):
    if lote_id is None:
        return
    lote = LoteEnvio.objects.filter(pk=lote_id, status=LoteEnvio.Status.LIBERADO).first()
    if lote and not lote.mensagens.filter(status__in=[M.Status.PENDENTE, M.Status.ENVIANDO, M.Status.RETIDA]).exists():
        lote.status = LoteEnvio.Status.CONCLUIDO
        lote.save(update_fields=["status", "atualizado_em"])
