"""Fluxo comercial: itens com preço do configurador, envio, link público, aprovação e conversão em venda."""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.catalogo.services import calcular_preco
from apps.core.agenda import ItemAtencao, atencao
from apps.core.models import Anexo
from apps.core.pdf import renderizar_pdf
from apps.core.services.notificacoes import notificar_papeis

from .models import ItemOrcamento, ItemVenda, Orcamento, Venda


class TransicaoInvalida(Exception):
    pass


def adicionar_item(orc: Orcamento, item_catalogo=None, quantidade=1, variacoes_ids=(), descricao="",
                   preco_unitario=None, desconto=Decimal("0")) -> ItemOrcamento:
    if not orc.editavel:
        raise TransicaoInvalida("Orçamento não pode mais ser alterado.")
    variacoes = []
    if item_catalogo is not None:
        calc = calcular_preco(item_catalogo, quantidade, variacoes_ids)
        variacoes = calc.get("variacoes", [])
        if preco_unitario in (None, ""):
            preco_unitario = calc["unitario"]
        descricao = descricao or item_catalogo.nome
    item = ItemOrcamento.objects.create(
        orcamento=orc, item_catalogo=item_catalogo, descricao=descricao, variacoes=variacoes,
        quantidade=Decimal(str(quantidade)), preco_unitario=Decimal(str(preco_unitario)), desconto=desconto or 0,
        ordem=orc.itens.count() + 1, empresa=orc.empresa,
    )
    orc.recalcular()
    return item


def link_publico(orc: Orcamento) -> str:
    return f"{settings.SITE_URL}{reverse('comercial_publico:publico', args=[orc.token_publico])}"


def gerar_pdf(orc: Orcamento) -> Anexo:
    pdf = renderizar_pdf("pdf/orcamento.html", {"o": orc, "itens": orc.itens.all(), "empresa": orc.empresa,
                                                 "link": link_publico(orc)})
    anexo = Anexo.criar(orc, f"{orc.numero}.pdf", pdf, descricao="Orçamento (PDF)")
    orc.pdf = anexo
    orc.save(update_fields=["pdf"])
    return anexo


def enviar(orc: Orcamento, email_destino: str | None = None) -> str:
    if not orc.itens.exists():
        raise TransicaoInvalida("Adicione ao menos um item antes de enviar.")
    if orc.status not in (Orcamento.Status.RASCUNHO, Orcamento.Status.ENVIADO, Orcamento.Status.VISUALIZADO):
        raise TransicaoInvalida("Orçamento já respondido.")
    anexo = gerar_pdf(orc)
    destino = email_destino or orc.email_cliente
    link = link_publico(orc)
    if destino:
        msg = EmailMessage(
            f"Orçamento {orc.numero} — {orc.empresa}",
            f"Olá!\n\nSegue o orçamento {orc.numero}, válido até {orc.validade:%d/%m/%Y}.\n"
            f"Você pode visualizar e aprovar online: {link}\n\nAtenciosamente,\n{orc.empresa}",
            settings.DEFAULT_FROM_EMAIL, [destino],
        )
        msg.attach(anexo.nome, anexo.ler(), "application/pdf")
        msg.send(fail_silently=True)
    if orc.status == Orcamento.Status.RASCUNHO:
        orc.status = Orcamento.Status.ENVIADO
    orc.enviado_em = timezone.now()
    orc.save(update_fields=["status", "enviado_em"])
    return link


def registrar_visualizacao(orc: Orcamento):
    if orc.status == Orcamento.Status.ENVIADO:
        orc.status = Orcamento.Status.VISUALIZADO
    if not orc.visualizado_em:
        orc.visualizado_em = timezone.now()
    orc.save(update_fields=["status", "visualizado_em"])


def aprovar(orc: Orcamento, nome: str, ip: str | None):
    if orc.expirado:
        raise TransicaoInvalida("Este orçamento expirou. Solicite um novo.")
    if orc.status not in (Orcamento.Status.ENVIADO, Orcamento.Status.VISUALIZADO):
        raise TransicaoInvalida("Este orçamento não está disponível para aprovação.")
    orc.status = Orcamento.Status.APROVADO
    orc.aprovado_em = timezone.now()
    orc.aprovado_por_nome = nome.strip()[:150]
    orc.ip_aprovacao = ip
    orc.save(update_fields=["status", "aprovado_em", "aprovado_por_nome", "ip_aprovacao"])
    notificar_papeis(["Administrador", "Financeiro"], f"Orçamento {orc.numero} aprovado por {orc.aprovado_por_nome}",
                     f"Total {orc.total}. Converta em venda.", nivel="success",
                     link=reverse("comercial:orcamento_detalhe", args=[orc.pk]), email=True, empresa=orc.empresa)


def solicitar_ajuste(orc: Orcamento, nome: str, texto: str):
    if orc.status not in (Orcamento.Status.ENVIADO, Orcamento.Status.VISUALIZADO):
        raise TransicaoInvalida("Este orçamento não aceita mais solicitações.")
    orc.ajuste_solicitado = f"{timezone.localtime():%d/%m/%Y %H:%M} — {nome}: {texto}\n{orc.ajuste_solicitado}"[:5000]
    orc.save(update_fields=["ajuste_solicitado"])
    notificar_papeis(["Administrador", "Financeiro"], f"Ajuste solicitado no orçamento {orc.numero}", texto[:500],
                     nivel="warning", link=reverse("comercial:orcamento_detalhe", args=[orc.pk]), email=True,
                     empresa=orc.empresa)


@transaction.atomic
def converter_em_venda(orc: Orcamento, parcelas=1, primeiro_vencimento=None) -> Venda:
    if orc.status != Orcamento.Status.APROVADO:
        raise TransicaoInvalida("Somente orçamentos aprovados podem ser convertidos.")
    venda = Venda.objects.create(
        orcamento=orc, cliente=orc.cliente, cliente_avulso_nome=orc.cliente_avulso_nome, total=orc.total,
        parcelas=parcelas, primeiro_vencimento=primeiro_vencimento or timezone.localdate(), empresa=orc.empresa,
        gera_nf=any(i.item_catalogo is None or i.item_catalogo.natureza == "SERVICO" for i in orc.itens.all()),
    )
    for i in orc.itens.all():
        ItemVenda.objects.create(venda=venda, item_catalogo=i.item_catalogo, descricao=i.descricao,
                                 variacoes=i.variacoes, quantidade=i.quantidade, preco_unitario=i.preco_unitario,
                                 desconto=i.desconto, total=i.total, empresa=orc.empresa)
    orc.status = Orcamento.Status.CONVERTIDO
    orc.save(update_fields=["status"])
    return venda


def expirar_orcamentos() -> int:
    return Orcamento.objects.filter(
        status__in=[Orcamento.Status.RASCUNHO, Orcamento.Status.ENVIADO, Orcamento.Status.VISUALIZADO],
        validade__lt=timezone.localdate(),
    ).update(status=Orcamento.Status.EXPIRADO)


def followup() -> int:
    """Lembrete 3 dias após o envio sem resposta (seção 11.2)."""
    limite = timezone.now() - timedelta(days=3)
    n = 0
    for o in Orcamento.objects.filter(status__in=[Orcamento.Status.ENVIADO, Orcamento.Status.VISUALIZADO],
                                      enviado_em__lte=limite, followup_em__isnull=True):
        notificar_papeis(["Administrador", "Financeiro"], f"Follow-up: orçamento {o.numero} sem resposta",
                         f"Enviado em {timezone.localtime(o.enviado_em):%d/%m/%Y} para {o.nome_cliente}.",
                         link=reverse("comercial:orcamento_detalhe", args=[o.pk]), empresa=o.empresa)
        o.followup_em = timezone.now()
        o.save(update_fields=["followup_em"])
        n += 1
    return n


@atencao
def _atencao_orcamentos(empresa, usuario):
    itens = []
    for o in Orcamento.objects.filter(empresa=empresa, status=Orcamento.Status.APROVADO):
        itens.append(ItemAtencao(f"Orçamento {o.numero} aprovado: converter em venda",
                                 reverse("comercial:orcamento_detalhe", args=[o.pk]), "success", 40, o.nome_cliente,
                                 "briefcase"))
    aguardando = Orcamento.objects.filter(empresa=empresa, status__in=["ENVIADO", "VISUALIZADO"]).count()
    if aguardando:
        itens.append(ItemAtencao(f"{aguardando} orçamento(s) aguardando resposta",
                                 reverse("comercial:orcamento_lista") + "?status=ENVIADO", "info", 70, "", "briefcase"))
    return itens
