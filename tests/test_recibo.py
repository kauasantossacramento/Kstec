"""Recibo de prestação de serviços: valor por extenso, PIX copia e cola e PDF arquivado na nota."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.extenso import reais
from apps.financeiro import pix


@pytest.mark.parametrize("valor,texto", [
    ("3500", "três mil e quinhentos reais"), ("2050", "dois mil e cinquenta reais"),
    ("4851", "quatro mil oitocentos e cinquenta e um reais"), ("1156.40", "mil cento e cinquenta e seis reais e quarenta centavos"),
    ("100", "cem reais"), ("1", "um real"), ("0.5", "cinquenta centavos"), ("1000000", "um milhão de reais"),
])
def test_valor_por_extenso(valor, texto):
    assert reais(Decimal(valor)) == texto


def test_pix_copia_e_cola_brcode():
    p = pix.copia_e_cola("62501281000113", "KS TEC SOLUÇÕES DE TECNOLOGIA LTDA", "Valença", Decimal("3500"), "NFSE-17")
    assert p.startswith("000201") and "0014br.gov.bcb.pix011462501281000113" in p and "54073500.00" in p
    assert "6007VALENCA" in p and "0506NFSE17" in p
    assert p[-4:] == pix.crc16(p[:-4])


def test_recibo_da_nota(cli, empresa, contrato, monkeypatch):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed
    from apps.fiscal.models import NotaFiscal, PerfilFiscal
    from apps.fiscal.services import recibo

    seed(empresa)
    nota = NotaFiscal.objects.create(empresa=empresa, tomador=contrato.cliente, contrato=contrato, competencia=contrato.vigencia_inicio,
                                     item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
                                     perfil=PerfilFiscal.objects.create(empresa=empresa, nome="P", aliquota_iss=Decimal("2")),
                                     valor_servicos=Decimal("3500"), valor_liquido=Decimal("3500"), ambiente=1,
                                     discriminacao="Manutenção de sistemas. Competência: Setembro/2026.\n\nChave PIX: 123",
                                     status="AUTORIZADA", numero_nfse="17")
    vistos = {}

    def falso(template, ctx):
        vistos.update(ctx)
        return b"%PDF-1.4 recibo"
    monkeypatch.setattr(recibo, "renderizar_pdf", falso)
    resposta = cli.get(reverse("fiscal:recibo", args=[nota.pk]) + "?novo=1")
    assert resposta.status_code == 200 and resposta["Content-Type"] == "application/pdf"
    assert vistos["valor_extenso"] == "três mil e quinhentos reais" and not vistos["pago"]
    assert vistos["descricao"] == "manutenção de sistemas"
    assert vistos["pix_copia_cola"].startswith("000201") and vistos["pix_qr"].startswith("data:image/png")
    assert "Recibo" in cli.get(reverse("fiscal:nota_detalhe", args=[nota.pk])).content.decode()
