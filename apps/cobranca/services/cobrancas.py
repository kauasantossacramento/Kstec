"""Orquestração de cobranças: cliente Asaas, cobrança idempotente, PIX e webhook com baixa opcional."""

import hmac
import secrets
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.models import Segredo
from apps.core.travas import TravaOcupada, trava
from apps.financeiro.models import Lancamento

from ..models import CobrancaAsaas, ConfiguracaoAsaas, Forma, PerfilCobranca
from .asaas import ClienteAsaas, ErroAsaas

FORMAS_BAIXA = {"PIX": "PIX", "BOLETO": "BOLETO", "CREDIT_CARD": "CARTAO", "DEBIT_CARD": "CARTAO",
                "TRANSFER": "TED", "DEPOSIT": "TED"}


def configuracao(empresa):
    config = ConfiguracaoAsaas.objects.select_related("api_key", "webhook_token", "empresa").filter(empresa=empresa).first()
    if not config or not config.pronta:
        raise ValidationError("Configure e ative a integração com o Asaas.")
    return config


@transaction.atomic
def salvar_configuracao(config, api_key=""):
    if api_key.strip():
        config.api_key = Segredo.criar("Asaas · chave de API", api_key.strip(), "INTEGRACAO", config.empresa)
    if not config.webhook_token_id:
        config.webhook_token = Segredo.criar("Asaas · token do webhook", secrets.token_urlsafe(32), "INTEGRACAO",
                                             config.empresa)
    if config.conta_recebimento and config.conta_recebimento.empresa_id != config.empresa_id:
        raise ValidationError("Conta de outra empresa.")
    config.full_clean()
    config.save()
    return config


def testar(config):
    with ClienteAsaas(config) as cli:
        dados = cli.conta()
    config.verificado_em = timezone.now()
    config.conta_nome = (dados.get("companyName") or dados.get("name") or "")[:200]
    config.save(update_fields=["verificado_em", "conta_nome", "atualizado_em"])
    return config


def perfil(pessoa):
    obj, _ = PerfilCobranca.objects.get_or_create(pessoa=pessoa, defaults={"empresa": pessoa.empresa})
    return obj


def garantir_cliente(cli, pessoa):
    p = perfil(pessoa)
    if p.asaas_cliente_id:
        return p.asaas_cliente_id
    existente = cli.buscar_cliente(pessoa.cpf_cnpj)
    if existente is None:
        from apps.core.validadores import normalizar_telefone

        corpo = {"name": pessoa.razao_social[:100], "cpfCnpj": pessoa.cpf_cnpj, "externalReference": str(pessoa.pk),
                 "notificationDisabled": True}
        if pessoa.email_destino_nf:
            corpo["email"] = pessoa.email_destino_nf
        telefone = normalizar_telefone(pessoa.telefone)
        if telefone:
            corpo["mobilePhone"] = telefone[2:]
        existente = cli.criar_cliente(corpo, objeto=pessoa)
    p.asaas_cliente_id = existente["id"]
    p.save(update_fields=["asaas_cliente_id", "atualizado_em"])
    return p.asaas_cliente_id


def _aplicar(cobranca, dados):
    cobranca.status = dados.get("status") or cobranca.status
    cobranca.link_fatura = dados.get("invoiceUrl") or cobranca.link_fatura
    cobranca.link_boleto = dados.get("bankSlipUrl") or cobranca.link_boleto
    if dados.get("value") is not None:
        cobranca.valor = Decimal(str(dados["value"]))
    if dados.get("dueDate"):
        cobranca.vencimento = parse_date(dados["dueDate"]) or cobranca.vencimento
    pago = dados.get("paymentDate") or dados.get("clientPaymentDate") or dados.get("confirmedDate")
    if pago and cobranca.status in CobrancaAsaas.PAGOS:
        cobranca.pago_em = parse_date(pago)
        bruto = dados.get("value")
        cobranca.valor_pago = Decimal(str(bruto)) if bruto is not None else cobranca.valor
    return cobranca


def _pix(cli, cobranca):
    if cobranca.forma not in (Forma.PIX, Forma.UNDEFINED, Forma.BOLETO) or not cobranca.aberta:
        return
    try:
        dados = cli.pix(cobranca.asaas_id)
    except ErroAsaas:
        return
    cobranca.pix_copia_cola = dados.get("payload", "")
    cobranca.pix_qr = dados.get("encodedImage", "")
    expira = dados.get("expirationDate")
    if expira:
        dt = parse_datetime(expira.replace(" ", "T"))
        cobranca.pix_expira = timezone.make_aware(dt) if dt and timezone.is_naive(dt) else dt


def cobrar_lancamento(lancamento, forma=None, nota=None, transporte=None):
    """Cria (ou reaproveita) a cobrança Asaas do lançamento. Seguro contra repetição e timeout."""
    if lancamento.tipo != "RECEITA" or lancamento.status in ("PAGO", "CANCELADO"):
        raise ValidationError("Somente receitas em aberto podem ser cobradas.")
    if not lancamento.pessoa_id:
        raise ValidationError("O lançamento precisa ter cliente para gerar cobrança.")
    existente = CobrancaAsaas.objects.filter(lancamento=lancamento, status__in=CobrancaAsaas.ABERTOS).first()
    if existente:
        return existente
    config = configuracao(lancamento.empresa)
    forma = forma or perfil(lancamento.pessoa).forma or config.forma_padrao
    referencia = f"lancamento:{lancamento.pk}"
    try:
        with trava(f"asaas:{referencia}", ttl=120):
            with ClienteAsaas(config, transporte) as cli:
                dados = cli.buscar_cobranca_por_referencia(referencia)
                if dados is None:
                    vencimento = max(lancamento.data_vencimento, timezone.localdate())
                    descricao = lancamento.descricao
                    if nota is not None and nota.numero_nfse:
                        descricao = f"NFS-e {nota.numero_nfse} · {nota.discriminacao[:300]}"
                    corpo = {"customer": garantir_cliente(cli, lancamento.pessoa), "billingType": forma,
                             "value": float(lancamento.valor), "dueDate": vencimento.isoformat(),
                             "description": descricao[:500], "externalReference": referencia}
                    if config.multa_pct:
                        corpo["fine"] = {"value": float(config.multa_pct), "type": "PERCENTAGE"}
                    if config.juros_mes_pct:
                        corpo["interest"] = {"value": float(config.juros_mes_pct)}
                    dados = cli.criar_cobranca(corpo, objeto=lancamento)
                cobranca = CobrancaAsaas.objects.filter(ambiente=config.ambiente, asaas_id=dados["id"]).first() \
                    or CobrancaAsaas(empresa=lancamento.empresa, lancamento=lancamento, nota=nota,
                                     ambiente=config.ambiente, asaas_id=dados["id"], forma=forma,
                                     valor=lancamento.valor, vencimento=lancamento.data_vencimento)
                _aplicar(cobranca, dados)
                _pix(cli, cobranca)
                cobranca.save()
                return cobranca
    except TravaOcupada:
        raise ValidationError("Cobrança deste lançamento já está sendo gerada.")


def cobrar_nota(nota, transporte=None):
    lancamento = Lancamento.objects.filter(nota_fiscal=nota).first()
    if lancamento is None:
        raise ValidationError("A nota ainda não tem recebível no financeiro.")
    perfil_cliente = perfil(nota.tomador)
    return cobrar_lancamento(lancamento, perfil_cliente.forma or None, nota=nota, transporte=transporte)


def sincronizar(cobranca, transporte=None):
    config = configuracao(cobranca.empresa)
    with ClienteAsaas(config, transporte) as cli:
        dados = cli.cobranca(cobranca.asaas_id)
        _aplicar(cobranca, dados)
        if cobranca.aberta and not cobranca.pix_copia_cola:
            _pix(cli, cobranca)
    cobranca.save()
    return registrar_pagamento(cobranca)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def config_por_token(token):
    if not token:
        return None
    for config in ConfiguracaoAsaas.objects.filter(ativo=True, webhook_token__isnull=False).select_related("webhook_token"):
        if hmac.compare_digest(config.webhook_token.ler().encode(), token.encode()):
            return config
    return None


def processar_webhook(config, payload):
    evento_id = str(payload.get("id") or "")
    evento = payload.get("event", "")
    dados = payload.get("payment") or {}
    if not dados.get("id"):
        return None
    with transaction.atomic():
        cobranca = CobrancaAsaas.objects.select_for_update().filter(ambiente=config.ambiente, asaas_id=dados["id"],
                                                                    empresa=config.empresa).first()
        if cobranca is None:
            return None
        if evento_id and any(e.get("id") == evento_id for e in cobranca.eventos):
            return cobranca
        _aplicar(cobranca, dados)
        cobranca.eventos = [*cobranca.eventos, {"id": evento_id, "evento": evento, "status": dados.get("status"),
                                                "em": timezone.now().isoformat(timespec="seconds")}][-60:]
        cobranca.save()
    return registrar_pagamento(cobranca)


def registrar_pagamento(cobranca):
    """Baixa o lançamento quando o Asaas confirma o pagamento (se a configuração permitir)."""
    if cobranca.status not in CobrancaAsaas.PAGOS:
        return cobranca
    lancamento = cobranca.lancamento
    if lancamento.status in ("PAGO", "CANCELADO"):
        return cobranca
    config = ConfiguracaoAsaas.objects.filter(empresa=cobranca.empresa).first()
    from apps.core.services.notificacoes import notificar_papeis
    from apps.core.templatetags.ks import brl

    texto = f"{lancamento.pessoa}: {brl(cobranca.valor_pago or cobranca.valor)} via Asaas ({cobranca.forma})."
    if config and config.baixa_automatica:
        from apps.financeiro.services.lancamentos import baixar

        try:
            baixar(lancamento, data_pagamento=min(cobranca.pago_em or timezone.localdate(), timezone.localdate()),
                   forma_pagamento=FORMAS_BAIXA.get(cobranca.forma, "PIX"),
                   juros=max((cobranca.valor_pago or cobranca.valor) - lancamento.valor, Decimal("0")),
                   desconto=max(lancamento.valor - (cobranca.valor_pago or cobranca.valor), Decimal("0")),
                   conta_bancaria=config.conta_recebimento)
            texto += " Baixa registrada."
        except ValidationError as erro:
            texto += " Baixa pendente: " + "; ".join(erro.messages)
    notificar_papeis(["Financeiro"], "Pagamento recebido", texto, nivel="success", empresa=cobranca.empresa,
                     link=f"/financeiro/lancamentos/{lancamento.pk}/", chave_dedup=f"asaas-pago:{cobranca.pk}")
    try:
        from apps.mensageria.services import alertas

        alertas.admin(cobranca.empresa, f"💰 Pagamento recebido\n{texto}", chave=f"asaas-pago:{cobranca.pk}")
    except Exception:  # noqa: BLE001 — aviso é complementar.
        pass
    return cobranca


def pix_vigente(cobranca):
    return bool(cobranca.pix_copia_cola) and (cobranca.pix_expira is None or cobranca.pix_expira > timezone.now())


def vencimento_valido(d: date):
    return max(d, timezone.localdate())
