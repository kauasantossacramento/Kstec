"""Reconhecimento de certidões, envio em lote, recebimento pela nota e inativação de contrato."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.certidoes import services as cert_services
from apps.certidoes.models import Certidao, TipoCertidao
from apps.contratos.services import alterar_situacao
from apps.faturamento.models import AgendaFaturamento
from apps.faturamento.services import ciclos, previsao


@pytest.fixture
def tipos(empresa):
    from apps.certidoes.seeds import seed

    seed(empresa)
    return TipoCertidao.objects.filter(empresa=empresa)


@pytest.mark.parametrize("texto,tipo,validade,situacao", [
    ("Certificado de Regularidade do FGTS - CRF ... Validade: 06/08/2026 a 04/09/2026 Certificação Número: 2026080617186522720330",
     "FGTS", date(2026, 9, 4), "NEGATIVA"),
    ("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS Certidão nº: 62150874/2026 Expedição: 16/07/2026, às 09:35 Validade: 12/01/2027",
     "CNDT", date(2027, 1, 12), "NEGATIVA"),
    ("RECEITA MUNICIPAL CERTIDÃO NEGATIVA DE DÉBITOS FISCAIS Nº 9878/2026 Data de Emissão: 11/08/2026 Validade: 30 DIAS",
     "Débitos Municipais", date(2026, 9, 10), "NEGATIVA"),
    ("PROCURADORIA-GERAL DA FAZENDA NACIONAL CERTIDÃO POSITIVA COM EFEITOS DE NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS "
     "FEDERAIS Emitida às 09:32:38 do dia 16/07/2026 Válida até 12/01/2027. Código de controle da certidão: 3F37.CA8C.8465.C11B",
     "Federal", date(2027, 1, 12), "POSITIVA_COM_EFEITO_NEGATIVA"),
])
def test_reconhecimento_de_certidoes(tipos, monkeypatch, texto, tipo, validade, situacao):
    monkeypatch.setattr(cert_services, "extrair_texto_pdf", lambda conteudo: texto)
    dados = cert_services.reconhecer(b"%PDF", tipos.first().empresa)
    assert tipo in dados["tipo"].nome
    assert dados["data_validade"] == validade and dados["situacao"] == situacao


def test_envio_em_lote_cadastra_e_nao_duplica(cli, tipos, monkeypatch):
    texto = ("CERTIDÃO NEGATIVA DE DÉBITOS TRABALHISTAS Certidão nº: 1/2026 Expedição: 16/07/2026 Validade: 12/01/2027")
    monkeypatch.setattr(cert_services, "extrair_texto_pdf", lambda conteudo: texto)

    def arquivos():
        return [SimpleUploadedFile("cndt.pdf", b"%PDF-1.4 x", "application/pdf"),
                SimpleUploadedFile("nao.pdf", b"nao e pdf", "application/pdf")]
    resposta = cli.post(reverse("certidoes:lote"), {"arquivos": arquivos()})
    assert resposta.status_code == 200 and Certidao.objects.count() == 1
    cli.post(reverse("certidoes:lote"), {"arquivos": arquivos()})
    assert Certidao.objects.count() == 1  # mesmo tipo e número: ignorada


def test_confirmar_recebimento_pela_nota(cli, empresa, contrato):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed
    from apps.financeiro.models import CategoriaFinanceira, ContaBancaria, Lancamento
    from apps.financeiro.services.lancamentos import centro_contrato
    from apps.fiscal.models import NotaFiscal, PerfilFiscal

    seed(empresa)
    nota = NotaFiscal.objects.create(empresa=empresa, tomador=contrato.cliente, contrato=contrato, competencia=date(2026, 9, 1),
                                     item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
                                     perfil=PerfilFiscal.objects.create(empresa=empresa, nome="P", aliquota_iss=Decimal("2")),
                                     valor_servicos=Decimal("100"), valor_liquido=Decimal("100"), discriminacao="x",
                                     status="AUTORIZADA", numero_nfse="99", ambiente=1)
    conta = ContaBancaria.objects.create(empresa=empresa, nome="BB")
    cat = CategoriaFinanceira.objects.create(empresa=empresa, nome="Rec", tipo="RECEITA", grupo_dre="RECEITA_BRUTA")
    lanc = Lancamento.objects.create(empresa=empresa, tipo="RECEITA", descricao="NFS-e 99", nota_fiscal=nota, categoria=cat,
                                     centro_custo=centro_contrato(contrato), valor=Decimal("100"), conta_bancaria=conta,
                                     data_competencia=date(2026, 9, 1), data_vencimento=date(2026, 10, 10))
    pagina = cli.get(reverse("fiscal:nota_detalhe", args=[nota.pk])).content.decode()
    assert "Confirmar recebimento" in pagina
    resposta = cli.post(reverse("fiscal:receber", args=[nota.pk]), {
        "data_pagamento": timezone.localdate().isoformat(), "forma_pagamento": "OB", "ordem_bancaria": "2026OB000123",
        "conta_bancaria": conta.pk})
    assert resposta.status_code == 302
    lanc.refresh_from_db()
    assert lanc.status == "PAGO" and lanc.ordem_bancaria == "2026OB000123"
    assert "Recebido em" in cli.get(reverse("fiscal:nota_detalhe", args=[nota.pk])).content.decode()


def test_inativar_contrato_pausa_faturamento_e_sai_das_contagens(cli, empresa, contrato):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed

    seed(empresa)
    agenda = AgendaFaturamento.objects.create(
        empresa=empresa, contrato=contrato, item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
        valor=Decimal("5000"), dia_emissao=5, hora_emissao=time(8), inicio=date(2026, 9, 1), ativa_desde=date(2026, 1, 1))
    ciclos.planejar(agenda, hoje=date(2026, 10, 1))
    assert previsao.mes(empresa, date(2026, 11, 1), hoje=date(2026, 10, 9))["total"] > 0
    with pytest.raises(ValidationError):
        alterar_situacao(contrato, "ENCERRADO", "")
    cli.post(reverse("contratos:situacao", args=[contrato.pk]), {"status": "ENCERRADO", "motivo": "Fim da vigência"})
    contrato.refresh_from_db()
    agenda.refresh_from_db()
    assert contrato.status == "ENCERRADO" and not agenda.ativo and contrato.motivo_situacao == "Fim da vigência"
    assert previsao.mes(empresa, date(2026, 11, 1), hoje=date(2026, 10, 9))["total"] == 0
    lista = cli.get(reverse("contratos:contrato_lista")).content.decode()
    assert contrato.numero not in lista
    assert contrato.numero in cli.get(reverse("contratos:contrato_lista") + "?todos=1").content.decode()
    hub = cli.get(reverse("contratos:contrato_detalhe", args=[contrato.pk])).content.decode()
    assert "Reativar" in hub and "Fim da vigência" in hub
    cli.post(reverse("contratos:situacao", args=[contrato.pk]), {"status": "VIGENTE", "motivo": "Reativado"})
    agenda.refresh_from_db()
    assert agenda.ativo


def test_datas_de_emissao_visiveis_no_contrato(cli, empresa, contrato):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed

    seed(empresa)
    agenda = AgendaFaturamento.objects.create(
        empresa=empresa, contrato=contrato, item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
        valor=Decimal("5000"), dia_emissao=7, hora_emissao=time(8), inicio=date(2026, 9, 1))
    hub = cli.get(reverse("contratos:contrato_detalhe", args=[contrato.pk])).content.decode()
    assert "todo dia 7" in hub and "Alterar datas" in hub
    wizard = cli.get(reverse("faturamento:agenda_editar", args=[agenda.pk]) + "?passo=3").content.decode()
    assert 'data-passo-inicial="3"' in wizard
