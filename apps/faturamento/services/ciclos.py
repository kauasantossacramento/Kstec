"""Planejamento e execução dos ciclos de faturamento.

Garantias:
- uma competência por agenda (constraint) e, por ciclo, uma única nota;
- a transmissão reutiliza `emissao.transmitir`, que bloqueia segunda tentativa da mesma nota;
- trava distribuída (Redis) + `select_for_update` impedem execução concorrente por workers/beat;
- chamadas externas ocorrem fora de transações de banco;
- resultado indeterminado vira TRANSMITIDO e é apenas consultado, nunca reenviado.
"""

from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.services.notificacoes import notificar_papeis
from apps.core.travas import TravaOcupada, trava
from apps.fiscal.models import ConfiguracaoFiscal, NotaFiscal
from apps.fiscal.services import emissao
from apps.fiscal.services.rascunhos import salvar as salvar_rascunho

from ..models import AgendaFaturamento, CicloFaturamento
from . import calendario

S = CicloFaturamento.Status
HORIZONTE_DIAS = 62
ATRASO_MAXIMO_DIAS = 20
REPETIR_BLOQUEADO_HORAS = 6
CONSULTA_MAXIMA_DIAS = 3


# ---------------------------------------------------------------------------
# Planejamento
# ---------------------------------------------------------------------------

def valores_previstos(agenda, previsto):
    return {"data_emissao": previsto.emissao, "data_vencimento": previsto.vencimento, "valor": agenda.valor}


@transaction.atomic
def planejar(agenda, hoje=None, horizonte_dias=HORIZONTE_DIAS):
    """Cria/sincroniza ciclos até o horizonte. Idempotente; não toca ciclos personalizados ou já executados."""
    hoje = hoje or timezone.localdate()
    agenda = AgendaFaturamento.objects.select_for_update(of=("self",)).select_related("contrato").get(pk=agenda.pk)
    if not agenda.ativo:
        return 0
    criados = 0
    for previsto in calendario.competencias(agenda, ate_emissao=hoje + timedelta(days=horizonte_dias)):
        if previsto.emissao < agenda.ativa_desde:
            continue
        ciclo = CicloFaturamento.objects.filter(agenda=agenda, competencia=previsto.competencia).first()
        if ciclo is None:
            ciclo = CicloFaturamento(empresa=agenda.empresa, agenda=agenda, competencia=previsto.competencia,
                                     **valores_previstos(agenda, previsto))
            ciclo.registrar("planejado", f"Emissão programada para {previsto.emissao:%d/%m/%Y}.")
            ciclo.save()
            criados += 1
        elif ciclo.status == S.PROGRAMADO and not ciclo.personalizado:
            novos = valores_previstos(agenda, previsto)
            if any(getattr(ciclo, k) != v for k, v in novos.items()):
                for k, v in novos.items():
                    setattr(ciclo, k, v)
                ciclo.registrar("sincronizado", "Datas e valor atualizados conforme a agenda.")
                ciclo.save()
    return criados


def planejar_todas(hoje=None):
    return sum(planejar(a, hoje) for a in AgendaFaturamento.objects.filter(ativo=True))


# ---------------------------------------------------------------------------
# Nota a partir do ciclo
# ---------------------------------------------------------------------------

AJUDA_PLACEHOLDERS = ("Use apenas: {competencia}, {mes_extenso}, {mes_nome}, {mes_nome_min}, {ano}, {parcela}, "
                      "{parcela2}, {total_parcelas}, {valor}, {contrato}, {empenho}, {objeto}.")


def discriminacao(ciclo):
    agenda, contrato = ciclo.agenda, ciclo.agenda.contrato
    modelo = ciclo.discriminacao or agenda.discriminacao or contrato.discriminacao_padrao \
        or "{objeto} — Competência {competencia}. Contrato nº {contrato}."
    parcela, total = calendario.parcela(contrato, ciclo.competencia)
    nome_mes = calendario.MESES[ciclo.competencia.month - 1]
    from apps.core.templatetags.ks import brl

    try:
        return modelo.format(competencia=f"{ciclo.competencia:%m/%Y}", mes_extenso=calendario.mes_extenso(ciclo.competencia),
                             mes_nome=nome_mes.capitalize(), mes_nome_min=nome_mes, ano=ciclo.competencia.year,
                             parcela=parcela, parcela2=f"{parcela:02d}", total_parcelas=total, valor=brl(ciclo.valor),
                             contrato=contrato.numero, objeto=contrato.objeto,
                             empenho=agenda.empenho.numero if agenda.empenho_id else "").strip()[:2000]
    except (KeyError, IndexError, ValueError) as erro:
        raise ValidationError(f"Modelo de discriminação inválido: {erro}. " + AJUDA_PLACEHOLDERS)


def checar_contrato(ciclo):
    contrato = ciclo.agenda.contrato
    if contrato.status != contrato.Status.VIGENTE:
        raise ValidationError(f"O contrato está {contrato.get_status_display().lower()}.")
    if not contrato.vigencia_inicio.replace(day=1) <= ciclo.competencia <= contrato.vigencia_fim_atual:
        raise ValidationError("A competência está fora da vigência do contrato.")
    if ciclo.valor > contrato.saldo:
        raise ValidationError(f"Saldo contratual insuficiente para {ciclo.valor} (saldo {contrato.saldo}).")


def criar_rascunho(ciclo, config):
    agenda = ciclo.agenda
    perfil = agenda.perfil or (config.perfil_padrao if config else None)
    if perfil is None:
        raise ValidationError("Defina o perfil fiscal da agenda ou o perfil padrão da configuração fiscal.")
    nota = NotaFiscal(empresa=ciclo.empresa, tomador=agenda.contrato.cliente, contrato=agenda.contrato,
                      item_catalogo=agenda.item_catalogo, perfil=perfil, competencia=ciclo.competencia,
                      discriminacao=discriminacao(ciclo), valor_servicos=ciclo.valor,
                      aliquota_iss=config.aliquota_iss if config else None,
                      vencimento_recebivel=ciclo.data_vencimento)
    return salvar_rascunho(nota)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def link(ciclo):
    return reverse("faturamento:ciclo", args=[ciclo.pk])


def avisar(ciclo, titulo, texto, nivel="info", whatsapp=True, confirmar=False):
    notificar_papeis(["Fiscal", "Financeiro"], titulo, texto, nivel=nivel, link=link(ciclo), empresa=ciclo.empresa,
                     chave_dedup=f"ciclo:{ciclo.pk}:{ciclo.status}")
    if whatsapp:
        from apps.mensageria.services import alertas

        alertas.ciclo(ciclo, titulo, texto, confirmar=confirmar)


def _marcar(ciclo, status, texto, tipo=None, usuario=None):
    ciclo.status = status
    ciclo.mensagem = texto[:500]
    ciclo.registrar(tipo or status.lower(), texto, usuario)
    ciclo.save()
    return ciclo


def executar(ciclo, usuario=None, manual=False):
    """Ponto de entrada do beat e do botão "Executar agora". Retorna o ciclo atualizado."""
    try:
        with trava(f"faturamento:ciclo:{ciclo.pk}", ttl=900):
            ciclo, transmitir_agora = _preparar(ciclo.pk, usuario, manual)
            if transmitir_agora:
                ciclo = transmitir(ciclo, usuario)
            return ciclo
    except TravaOcupada:
        raise ValidationError("Este ciclo já está sendo processado. Aguarde alguns instantes.")


def _preparar(pk, usuario, manual):
    with transaction.atomic():
        ciclo = CicloFaturamento.objects.select_for_update(of=("self",)).select_related(
            "agenda__contrato__cliente", "agenda__item_catalogo", "agenda__perfil", "nota").get(pk=pk)
        if ciclo.status not in (S.PROGRAMADO, S.BLOQUEADO, S.FALHA):
            return ciclo, False
        if ciclo.status == S.FALHA and not manual:
            return ciclo, False
        hoje = timezone.localdate()
        if not manual and (hoje - ciclo.data_emissao).days > ATRASO_MAXIMO_DIAS:
            _marcar(ciclo, S.BLOQUEADO, "Emissão atrasada há mais de 20 dias. Confira e execute manualmente.")
            transaction.on_commit(lambda: avisar(ciclo, "Faturamento atrasado", ciclo.mensagem, "warning"))
            return ciclo, False
        ciclo.execucoes += 1
        ciclo.ultima_execucao = timezone.now()
        config = ConfiguracaoFiscal.objects.select_related("empresa", "certificado", "perfil_padrao").filter(
            empresa=ciclo.empresa).first()
        anterior = ciclo.status
        try:
            checar_contrato(ciclo)
            if ciclo.nota_id is None:
                ciclo.nota = criar_rascunho(ciclo, config)
                ciclo.registrar("rascunho", "Rascunho da NFS-e calculado e salvo.", usuario)
            elif ciclo.nota.status == NotaFiscal.Status.REJEITADA:
                raise ValidationError("A nota anterior foi rejeitada. Use “Refazer nota” após corrigir a causa.")
            if ciclo.agenda.modo == AgendaFaturamento.Modo.RASCUNHO:
                _marcar(ciclo, S.RASCUNHO, "Rascunho pronto. Revise e transmita pela tela da nota.", usuario=usuario)
                transaction.on_commit(lambda: avisar(ciclo, "Rascunho de NFS-e pronto",
                                                     f"{ciclo}: revise e transmita.", "info"))
                return ciclo, False
            if config is None:
                raise ValidationError("Cadastre a configuração fiscal.")
            emissao.validar_emissao(ciclo.nota, config)
        except ValidationError as erro:
            texto = "; ".join(erro.messages)
            _marcar(ciclo, S.BLOQUEADO, texto, "bloqueio", usuario)
            if anterior != S.BLOQUEADO or manual:
                transaction.on_commit(lambda: avisar(ciclo, "Faturamento bloqueado", f"{ciclo}: {texto}", "warning"))
            return ciclo, False
        if ciclo.agenda.modo == AgendaFaturamento.Modo.CONFIRMAR and not manual:
            _marcar(ciclo, S.AGUARDANDO, "Nota validada. Aguardando sua confirmação para transmitir.", usuario=usuario)
            transaction.on_commit(lambda: avisar(ciclo, "Confirme a emissão da NFS-e",
                                                 resumo(ciclo), "warning", confirmar=True))
            return ciclo, False
        ciclo.save()
        return ciclo, True


def resumo(ciclo):
    from apps.core.templatetags.ks import brl

    a = ciclo.agenda
    return (f"{a.contrato.cliente} · contrato {a.contrato.numero}\n"
            f"Competência {ciclo.competencia:%m/%Y} · valor {brl(ciclo.valor)}\n"
            f"Vencimento previsto {ciclo.data_vencimento:%d/%m/%Y}")


def confirmar(ciclo, usuario=None, origem="aplicativo"):
    """Libera a transmissão de um ciclo em AGUARDANDO (pela tela ou pelo WhatsApp)."""
    try:
        with trava(f"faturamento:ciclo:{ciclo.pk}", ttl=900):
            with transaction.atomic():
                ciclo = CicloFaturamento.objects.select_for_update(of=("self",)).select_related("nota", "agenda").get(pk=ciclo.pk)
                if ciclo.status != S.AGUARDANDO:
                    raise ValidationError("Este ciclo não está aguardando confirmação.")
                ciclo.confirmado_por = usuario if getattr(usuario, "pk", None) else None
                ciclo.confirmado_em = timezone.now()
                ciclo.registrar("confirmado", f"Transmissão confirmada via {origem}.", usuario)
                ciclo.save()
            from apps.mensageria.services import confirmacoes

            confirmacoes.cancelar_pendentes(ciclo.empresa, "faturamento.transmitir", ciclo.pk, f"confirmado via {origem}")
            return transmitir(ciclo, usuario)
    except TravaOcupada:
        raise ValidationError("Este ciclo já está sendo processado.")


def transmitir(ciclo, usuario=None):
    nota = ciclo.nota
    try:
        emissao.transmitir(nota)
    except ValidationError as erro:
        nota.refresh_from_db()
        texto = "; ".join(erro.messages)
        with transaction.atomic():
            ciclo = CicloFaturamento.objects.select_for_update().get(pk=ciclo.pk)
            if nota.tentativas.exists():
                _marcar(ciclo, S.TRANSMITIDO, "Envio realizado; resultado será consultado automaticamente.", "transmitido", usuario)
            else:
                _marcar(ciclo, S.BLOQUEADO, texto, "bloqueio", usuario)
        if ciclo.status == S.BLOQUEADO:
            avisar(ciclo, "Faturamento bloqueado", f"{ciclo}: {texto}", "warning")
        return ciclo
    return atualizar_por_nota(ciclo, usuario)


def atualizar_por_nota(ciclo, usuario=None):
    with transaction.atomic():
        ciclo = CicloFaturamento.objects.select_for_update(of=("self",)).select_related("nota", "agenda__contrato").get(pk=ciclo.pk)
        nota = ciclo.nota
        if ciclo.status == S.AUTORIZADO or nota is None:
            return ciclo
        if nota.status == NotaFiscal.Status.AUTORIZADA:
            _marcar(ciclo, S.AUTORIZADO, f"NFS-e {nota.numero_nfse} autorizada.", "autorizado", usuario)
            transaction.on_commit(lambda: pos_autorizacao(ciclo))
        elif nota.status == NotaFiscal.Status.REJEITADA:
            erros = (nota.tentativas.first().resposta or {}).get("erros") if nota.tentativas.exists() else None
            _marcar(ciclo, S.FALHA, f"Nota rejeitada pelo emissor. {erros or ''}".strip(), "rejeitada", usuario)
            transaction.on_commit(lambda: avisar(ciclo, "NFS-e rejeitada", f"{ciclo}: verifique a nota.", "danger"))
        elif ciclo.status != S.TRANSMITIDO:
            _marcar(ciclo, S.TRANSMITIDO, "Transmitida; resultado será consultado automaticamente.", "transmitido", usuario)
    return ciclo


def pos_autorizacao(ciclo):
    """PDF, cobrança Asaas e envio ao cliente. Falhas aqui não afetam a autorização fiscal."""
    from apps.fiscal.services.pdf_nfse import garantir_pdf

    nota = ciclo.nota
    passos = []
    try:
        garantir_pdf(nota)
        passos.append("DANFSe gerado")
    except Exception as erro:  # noqa: BLE001 — PDF é complementar; registra e segue.
        passos.append(f"PDF pendente: {erro}")
    if ciclo.agenda.gerar_cobranca:
        try:
            from apps.cobranca.services import cobrancas

            cobrancas.cobrar_nota(nota)
            passos.append("cobrança Asaas criada")
        except Exception as erro:  # noqa: BLE001
            passos.append(f"cobrança pendente: {erro}")
    if ciclo.agenda.enviar_whatsapp:
        try:
            from apps.mensageria.services import envios

            lote = envios.preparar_envio_nota(nota)
            passos.append(f"envio WhatsApp {lote.get_status_display().lower()}" if lote else "sem contato WhatsApp autorizado")
        except Exception as erro:  # noqa: BLE001
            passos.append(f"WhatsApp pendente: {erro}")
    with transaction.atomic():
        atual = CicloFaturamento.objects.select_for_update().get(pk=ciclo.pk)
        atual.registrar("pos_autorizacao", "; ".join(passos))
        atual.save()
    avisar(ciclo, "NFS-e autorizada", f"{ciclo}: NFS-e {nota.numero_nfse}. " + "; ".join(passos), "success")


def acompanhar(agora=None):
    """Consulta (sem reenviar) notas transmitidas cujo resultado ainda é desconhecido."""
    agora = agora or timezone.now()
    total = 0
    # Rascunhos/aguardando transmitidos manualmente pela tela fiscal acompanham a nota.
    for ciclo in CicloFaturamento.objects.filter(status__in=[S.RASCUNHO, S.AGUARDANDO]).exclude(
            nota__status=NotaFiscal.Status.RASCUNHO).exclude(nota__isnull=True):
        atualizar_por_nota(ciclo)
    for ciclo in CicloFaturamento.objects.filter(status=S.TRANSMITIDO).select_related("nota"):
        nota = ciclo.nota
        if nota.status in (NotaFiscal.Status.AUTORIZADA, NotaFiscal.Status.REJEITADA):
            atualizar_por_nota(ciclo)
            continue
        if ciclo.ultima_execucao and agora - ciclo.ultima_execucao > timedelta(days=CONSULTA_MAXIMA_DIAS):
            with transaction.atomic():
                _marcar(CicloFaturamento.objects.select_for_update().get(pk=ciclo.pk), S.FALHA,
                        "Resultado não confirmado após 3 dias de consultas. Consulte a DPS manualmente.")
            continue
        try:
            with trava(f"faturamento:ciclo:{ciclo.pk}", ttl=300):
                emissao.consultar(nota)
        except TravaOcupada:
            continue
        except Exception as erro:  # noqa: BLE001 — indisponibilidade: tenta na próxima rodada.
            with transaction.atomic():
                c = CicloFaturamento.objects.select_for_update().get(pk=ciclo.pk)
                c.registrar("consulta", f"Consulta indisponível: {str(erro)[:200]}")
                c.save()
            continue
        atualizar_por_nota(ciclo)
        total += 1
    return total


def pendentes(agora=None):
    agora = timezone.localtime(agora or timezone.now())
    hoje = agora.date()
    qs = CicloFaturamento.objects.filter(agenda__ativo=True, data_emissao__lte=hoje,
                                         status__in=[S.PROGRAMADO, S.BLOQUEADO]).select_related("agenda")
    limite_bloqueado = agora - timedelta(hours=REPETIR_BLOQUEADO_HORAS)
    for ciclo in qs:
        if ciclo.data_emissao == hoje and agora.time() < ciclo.agenda.hora_emissao:
            continue
        if ciclo.status == S.BLOQUEADO and ciclo.ultima_execucao and ciclo.ultima_execucao > limite_bloqueado:
            continue
        yield ciclo


def processar(agora=None):
    total = 0
    for ciclo in list(pendentes(agora)):
        try:
            executar(ciclo)
            total += 1
        except ValidationError:
            continue
    return total


# ---------------------------------------------------------------------------
# Ações manuais
# ---------------------------------------------------------------------------

@transaction.atomic
def ajustar(ciclo, *, valor, data_emissao, data_vencimento, discriminacao_texto, usuario=None):
    ciclo = CicloFaturamento.objects.select_for_update().get(pk=ciclo.pk)
    if ciclo.status not in CicloFaturamento.EDITAVEIS:
        raise ValidationError("Só é possível ajustar ciclos programados ou bloqueados, antes de gerar a nota.")
    if ciclo.nota_id:
        raise ValidationError("A nota deste ciclo já foi gerada; edite o rascunho na tela da nota.")
    if data_vencimento < data_emissao:
        raise ValidationError("O vencimento deve ser igual ou posterior à emissão.")
    ciclo.valor, ciclo.data_emissao, ciclo.data_vencimento = valor, data_emissao, data_vencimento
    ciclo.discriminacao = discriminacao_texto
    ciclo.personalizado = True
    if ciclo.status == S.BLOQUEADO:
        ciclo.status = S.PROGRAMADO
        ciclo.ultima_execucao = None
    ciclo.registrar("ajuste", f"Ajustado: valor {valor}, emissão {data_emissao:%d/%m/%Y}, "
                              f"vencimento {data_vencimento:%d/%m/%Y}.", usuario)
    ciclo.full_clean()
    ciclo.save()
    return ciclo


@transaction.atomic
def pular(ciclo, motivo, usuario=None):
    ciclo = CicloFaturamento.objects.select_for_update(of=("self",)).select_related("nota").get(pk=ciclo.pk)
    if ciclo.status in (S.AUTORIZADO, S.TRANSMITIDO, S.PULADO):
        raise ValidationError("Este ciclo não pode mais ser pulado.")
    if ciclo.nota_id and ciclo.nota.status != NotaFiscal.Status.RASCUNHO and ciclo.nota.status != NotaFiscal.Status.REJEITADA:
        raise ValidationError("A nota deste ciclo já foi transmitida.")
    if not motivo.strip():
        raise ValidationError("Informe o motivo.")
    return _marcar(ciclo, S.PULADO, f"Competência não será faturada: {motivo.strip()}", "pulado", usuario)


@transaction.atomic
def retomar(ciclo, usuario=None):
    """Volta um ciclo pulado/bloqueado para a fila (sem gerar nada imediatamente)."""
    ciclo = CicloFaturamento.objects.select_for_update().get(pk=ciclo.pk)
    if ciclo.status not in (S.PULADO, S.BLOQUEADO) or (ciclo.nota_id and ciclo.nota.status != NotaFiscal.Status.RASCUNHO):
        raise ValidationError("Somente ciclos pulados ou bloqueados podem voltar à fila.")
    ciclo.ultima_execucao = None
    return _marcar(ciclo, S.PROGRAMADO, "Ciclo devolvido à fila de emissão.", "retomado", usuario)


@transaction.atomic
def refazer(ciclo, usuario=None):
    """Desvincula a nota rejeitada (que permanece no histórico fiscal) para gerar uma nova."""
    ciclo = CicloFaturamento.objects.select_for_update(of=("self",)).select_related("nota").get(pk=ciclo.pk)
    if ciclo.status != S.FALHA or not ciclo.nota_id or ciclo.nota.status != NotaFiscal.Status.REJEITADA:
        raise ValidationError("Refazer só se aplica a ciclos com nota rejeitada.")
    anterior = ciclo.nota
    ciclo.nota = None
    ciclo.ultima_execucao = None
    return _marcar(ciclo, S.PROGRAMADO, f"Nota rejeitada {str(anterior.pk)[:8]} preservada no histórico; nova nota será gerada.",
                   "refazer", usuario)


def proxima_execucao(agenda):
    ciclo = agenda.ciclos.filter(status__in=[S.PROGRAMADO, S.BLOQUEADO, S.AGUARDANDO]).order_by("data_emissao").first()
    if ciclo:
        return ciclo
    futuros = calendario.simular(agenda, 1, max(timezone.localdate(), agenda.ativa_desde))
    return futuros[0] if futuros else None


def datahora_emissao(ciclo):
    return timezone.make_aware(datetime.combine(ciclo.data_emissao, ciclo.agenda.hora_emissao))
