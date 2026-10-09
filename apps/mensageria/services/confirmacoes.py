"""Confirmações por código, respondidas pelo WhatsApp (SIM 1234 / NAO 1234) ou pela tela.

Cada ação registra um executor. O código é curto, aleatório e único entre pendentes da empresa.
"""

import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import Confirmacao

ACOES = {}


def acao(nome):
    def deco(fn):
        ACOES[nome] = fn
        return fn
    return deco


def novo_codigo(empresa):
    for _ in range(50):
        codigo = f"{secrets.randbelow(9000) + 1000}"
        if not Confirmacao.objects.filter(empresa=empresa, codigo=codigo, status=Confirmacao.Status.PENDENTE).exists():
            return codigo
    raise ValidationError("Não foi possível gerar código de confirmação.")


def criar(empresa, nome_acao, objeto, descricao, horas=24, dados=None):
    existente = Confirmacao.objects.filter(empresa=empresa, acao=nome_acao, objeto_id=str(objeto.pk),
                                           status=Confirmacao.Status.PENDENTE).first() if dados is None else None
    if existente:
        return existente
    c = Confirmacao(empresa=empresa, codigo=novo_codigo(empresa), acao=nome_acao, objeto_id=str(objeto.pk),
                    descricao=descricao[:300], expira_em=timezone.now() + timedelta(hours=horas), dados=dados or {})
    c.save()
    return c


def responder(empresa, codigo, aceitar, por="WhatsApp"):
    with transaction.atomic():
        c = Confirmacao.objects.select_for_update().filter(empresa=empresa, codigo=str(codigo).strip(),
                                                           status=Confirmacao.Status.PENDENTE).first()
        if c is None:
            return None, "Código não encontrado ou já respondido."
        if c.expira_em < timezone.now():
            c.status = Confirmacao.Status.EXPIRADA
            c.save()
            return c, "Este código expirou."
        c.status = Confirmacao.Status.CONFIRMADA if aceitar else Confirmacao.Status.RECUSADA
        c.respondida_em = timezone.now()
        c.respondida_por = por[:120]
        c.save()
    executor = ACOES.get(c.acao)
    try:
        resultado = executor(c, aceitar, por) if executor else "Ação desconhecida."
    except ValidationError as erro:
        resultado = "Não foi possível concluir: " + "; ".join(erro.messages)
    Confirmacao.objects.filter(pk=c.pk).update(resultado=str(resultado)[:300])
    return c, resultado


def cancelar_pendentes(empresa, nome_acao, objeto_id, motivo="resolvido pela tela"):
    Confirmacao.objects.filter(empresa=empresa, acao=nome_acao, objeto_id=str(objeto_id),
                               status=Confirmacao.Status.PENDENTE).update(
        status=Confirmacao.Status.RECUSADA, respondida_em=timezone.now(), respondida_por=motivo[:120])


def expirar(empresa=None, agora=None):
    agora = agora or timezone.now()
    qs = Confirmacao.objects.filter(status=Confirmacao.Status.PENDENTE, expira_em__lt=agora)
    if empresa:
        qs = qs.filter(empresa=empresa)
    total = 0
    for c in qs:
        with transaction.atomic():
            atual = Confirmacao.objects.select_for_update().get(pk=c.pk)
            if atual.status != Confirmacao.Status.PENDENTE:
                continue
            atual.status = Confirmacao.Status.EXPIRADA
            atual.save()
        expirada = ACOES.get(f"{c.acao}:expirada")
        if expirada:
            expirada(c)
        total += 1
    return total


# ---------------------------------------------------------------------------
# Ações registradas
# ---------------------------------------------------------------------------

@acao("faturamento.transmitir")
def _transmitir(c, aceitar, por):
    from apps.faturamento.models import CicloFaturamento
    from apps.faturamento.services import ciclos

    ciclo = CicloFaturamento.objects.filter(pk=c.objeto_id, empresa=c.empresa).first()
    if ciclo is None:
        return "Ciclo não encontrado."
    if not aceitar:
        ciclo.registrar("recusado", f"Transmissão não autorizada via {por}. Ciclo permanece aguardando.")
        ciclo.save()
        return "Ok, não transmiti. O ciclo segue aguardando na tela de faturamento."
    ciclo = ciclos.confirmar(ciclo, None, origem=por)
    return ciclo.mensagem or ciclo.get_status_display()


@acao("mensageria.lote")
def _lote(c, aceitar, por):
    from . import envios

    lote = envios.lote_de(c)
    if lote is None:
        return "Envio não encontrado."
    if aceitar:
        envios.liberar(lote, por)
        return f"Liberado: {lote.mensagens.count()} mensagem(ns) entrarão na fila respeitando o ritmo seguro."
    envios.cancelar(lote, por)
    return "Envio cancelado. Nada foi enviado ao cliente."


@acao("mensageria.lote:expirada")
def _lote_expirado(c):
    from . import envios
    from .fila import config_de

    lote = envios.lote_de(c)
    if lote is None:
        return
    regra = config_de(c.empresa).sem_resposta
    if regra == "ENVIAR":
        envios.liberar(lote, "prazo expirado (enviar)")
    elif regra == "CANCELAR":
        envios.cancelar(lote, "prazo expirado", expirado=True)
    else:
        # AGUARDAR: renova o pedido pelo mesmo prazo, sem novo aviso.
        Confirmacao.objects.filter(pk=c.pk).update(status=Confirmacao.Status.PENDENTE,
                                                   expira_em=timezone.now() + timedelta(hours=24))
