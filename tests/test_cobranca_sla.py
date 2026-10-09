"""Asaas (API simulada, idempotência, webhook com baixa) e monitoramento (queda, incidente e alerta)."""

import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from apps.cobranca.models import CobrancaAsaas, ConfiguracaoAsaas
from apps.cobranca.services import cobrancas
from apps.financeiro.models import CategoriaFinanceira, ContaBancaria, Lancamento
from apps.financeiro.services.lancamentos import centro_contrato
from apps.mensageria.models import MensagemWhatsApp
from apps.mensageria.services import fila
from apps.sla.models import Incidente, Sistema
from apps.sla.services import monitor


class AsaasFalso:
    def __init__(self):
        self.chamadas = []
        self.cobrancas = {}

    def __call__(self, request):
        self.chamadas.append((request.method, request.url.path))
        assert request.headers["access_token"] == "chave-sandbox"
        caminho = request.url.path.removeprefix("/v3")
        if caminho == "/customers" and request.method == "GET":
            return httpx.Response(200, json={"data": []})
        if caminho == "/customers":
            return httpx.Response(200, json={"id": "cus_1"})
        if caminho == "/payments" and request.method == "GET":
            ref = request.url.params.get("externalReference")
            achadas = [p for p in self.cobrancas.values() if p["externalReference"] == ref]
            return httpx.Response(200, json={"data": achadas})
        if caminho == "/payments":
            corpo = json.loads(request.content)
            pid = f"pay_{len(self.cobrancas) + 1}"
            self.cobrancas[pid] = {"id": pid, "status": "PENDING", "value": corpo["value"], "dueDate": corpo["dueDate"],
                                   "invoiceUrl": f"https://sandbox.asaas.com/i/{pid}", "externalReference": corpo["externalReference"]}
            return httpx.Response(200, json=self.cobrancas[pid])
        if caminho.endswith("/pixQrCode"):
            return httpx.Response(200, json={"encodedImage": "iVBORw0KGgo=", "payload": "00020126PIX",
                                             "expirationDate": "2026-12-31 23:59:59"})
        return httpx.Response(404, json={"errors": [{"description": "não encontrado"}]})


@pytest.fixture
def asaas(empresa):
    conta = ContaBancaria.objects.create(empresa=empresa, nome="Asaas")
    config = cobrancas.salvar_configuracao(ConfiguracaoAsaas(empresa=empresa, conta_recebimento=conta), "chave-sandbox")
    return config


@pytest.fixture
def lancamento(contrato):
    categoria = CategoriaFinanceira.objects.create(empresa=contrato.empresa, nome="Contratos públicos", tipo="RECEITA",
                                                   grupo_dre="RECEITA_BRUTA")
    return Lancamento.objects.create(empresa=contrato.empresa, tipo="RECEITA", descricao="NFS-e 77", pessoa=contrato.cliente,
                                     categoria=categoria, centro_custo=centro_contrato(contrato), valor=Decimal("5000"),
                                     data_competencia=date(2026, 9, 1), data_vencimento=timezone.localdate() + timedelta(days=20))


def test_chaves_cifradas(asaas):
    assert asaas.api_key.ler() == "chave-sandbox"
    assert b"chave-sandbox" not in bytes(asaas.api_key.valor_criptografado)
    assert len(asaas.webhook_token.ler()) >= 32


def test_cobranca_idempotente_com_pix(asaas, lancamento):
    falso = AsaasFalso()
    transporte = httpx.MockTransport(falso)
    cobranca = cobrancas.cobrar_lancamento(lancamento, transporte=transporte)
    assert cobranca.asaas_id == "pay_1" and cobranca.pix_copia_cola == "00020126PIX" and cobranca.link_fatura
    assert cobrancas.cobrar_lancamento(lancamento, transporte=transporte).pk == cobranca.pk
    assert sum(1 for m, p in falso.chamadas if m == "POST" and p.endswith("/payments")) == 1
    # Timeout após o POST: a cobrança existente no Asaas é reaproveitada pela referência externa.
    CobrancaAsaas.objects.all().delete()
    cobrancas.cobrar_lancamento(lancamento, transporte=transporte)
    assert sum(1 for m, p in falso.chamadas if m == "POST" and p.endswith("/payments")) == 1


def test_webhook_autentica_baixa_e_ignora_repeticao(client, asaas, lancamento):
    cobrancas.cobrar_lancamento(lancamento, transporte=httpx.MockTransport(AsaasFalso()))
    url = reverse("cobranca:webhook")
    corpo = {"id": "evt_1", "event": "PAYMENT_RECEIVED",
             "payment": {"id": "pay_1", "status": "RECEIVED", "value": 5000, "billingType": "PIX",
                         "paymentDate": timezone.localdate().isoformat()}}
    assert client.post(url, corpo, content_type="application/json", HTTP_ASAAS_ACCESS_TOKEN="errado").status_code == 401
    token = asaas.webhook_token.ler()
    assert client.post(url, corpo, content_type="application/json", HTTP_ASAAS_ACCESS_TOKEN=token).status_code == 200
    lancamento.refresh_from_db()
    assert lancamento.status == "PAGO" and lancamento.forma_pagamento in ("PIX", "BOLETO")
    assert client.post(url, corpo, content_type="application/json", HTTP_ASAAS_ACCESS_TOKEN=token).status_code == 200
    assert len(CobrancaAsaas.objects.get().eventos) == 1


def test_erro_da_api_vira_mensagem_clara(asaas, lancamento):
    transporte = httpx.MockTransport(lambda r: httpx.Response(400, json={"errors": [{"description": "CPF inválido"}]}))
    with pytest.raises(Exception, match="CPF inválido"):
        cobrancas.cobrar_lancamento(lancamento, transporte=transporte)


def test_telas_cobranca(cli, asaas, lancamento):
    assert cli.get(reverse("cobranca:configuracao")).status_code == 200
    cobranca = cobrancas.cobrar_lancamento(lancamento, transporte=httpx.MockTransport(AsaasFalso()))
    assert cli.get(reverse("cobranca:cobranca_detalhe", args=[cobranca.pk])).status_code == 200
    assert cli.get(reverse("financeiro:lancamento_detalhe", args=[lancamento.pk])).status_code == 200


# ---------------------------------------------------------------------------
# Monitoramento
# ---------------------------------------------------------------------------

@pytest.fixture
def sistema(empresa):
    config = fila.config_de(empresa)
    config.ativo, config.numeros_admin = True, "5575999990000"
    config.save()
    return Sistema.objects.create(empresa=empresa, nome="Portal da Transparência", url="https://portal.example.gov.br",
                                  palavra_chave="Transparência", falhas_para_alerta=2)


def test_queda_abre_incidente_alerta_e_retorno_fecha(sistema, django_capture_on_commit_callbacks):
    ok = httpx.MockTransport(lambda r: httpx.Response(200, text="Portal da Transparência"))
    fora = httpx.MockTransport(lambda r: httpx.Response(503))
    assert monitor.verificar(sistema, ok).status == "OPERACIONAL"
    assert monitor.verificar(sistema, fora).status == "OPERACIONAL"  # uma falha isolada não alerta
    with django_capture_on_commit_callbacks(execute=True):
        s = monitor.verificar(sistema, fora)
    assert s.status == "FORA" and Incidente.objects.filter(status="ABERTO").count() == 1
    assert MensagemWhatsApp.objects.filter(para_admin=True, texto__contains="fora do ar").exists()
    with django_capture_on_commit_callbacks(execute=True):
        s = monitor.verificar(sistema, ok)
    assert s.status == "OPERACIONAL" and Incidente.objects.get().status == "FECHADO"
    assert MensagemWhatsApp.objects.filter(para_admin=True, texto__contains="voltou").exists()
    assert s.uptime(30) == 50.0


def test_texto_esperado_ausente_e_timeout(sistema):
    sucesso, http, _, erro = monitor.checar(sistema, httpx.MockTransport(lambda r: httpx.Response(200, text="Erro 500")))
    assert not sucesso and http == 200 and "Texto esperado" in erro

    def lento(request):
        raise httpx.ReadTimeout("lento", request=request)
    assert "Sem resposta" in monitor.checar(sistema, httpx.MockTransport(lento))[3]


def test_manutencao_nao_alerta(sistema, django_capture_on_commit_callbacks):
    sistema.em_manutencao = True
    sistema.save()
    fora = httpx.MockTransport(lambda r: httpx.Response(503))
    with django_capture_on_commit_callbacks(execute=True):
        monitor.verificar(sistema, fora)
        s = monitor.verificar(sistema, fora)
    assert s.status == "MANUTENCAO" and not MensagemWhatsApp.objects.exists()


def test_telas_monitoramento(cli, sistema):
    monitor.verificar(sistema, httpx.MockTransport(lambda r: httpx.Response(200, text="Transparência")))
    for url in (reverse("sla:home"), reverse("sla:sistema_detalhe", args=[sistema.pk]), reverse("sla:sistema_novo")):
        assert cli.get(url).status_code == 200, url
