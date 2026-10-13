"""Assinatura digital (PAdES), prévia de relatório/planilha, texto-base do relatório e propagação da data de emissão."""

import io
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter

from apps.core.models import CertificadoAssinatura
from apps.core.services import assinatura
from apps.faturamento.models import AgendaFaturamento, CicloFaturamento
from apps.faturamento.services import ciclos

SENHA = "senha-de-teste"


def pfx_sintetico(nome="EMPRESA SINTETICA LTDA:00000000000000"):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeito = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome)])
    agora = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(sujeito).issuer_name(sujeito).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=1))
            .not_valid_after(agora + timedelta(days=30))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
            .sign(chave, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(b"teste", chave, cert, None, BestAvailableEncryption(SENHA.encode()))


def pdf_minimo():
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    w.write(buf)
    return buf.getvalue()


def test_cadastro_e_assinatura_pades(empresa):
    c = assinatura.cadastrar(empresa, pfx_sintetico(), SENHA, "EMPRESA")
    assert c.padrao and c.valido and c.titular.startswith("EMPRESA SINTETICA")
    pdf, titular = assinatura.assinar_pdf(pdf_minimo(), empresa, "Teste")
    assert titular == c.titular and assinatura.esta_assinado(pdf)
    assert not assinatura.esta_assinado(pdf_minimo())


def test_sem_certificado_segue_sem_assinatura(empresa):
    pdf, titular = assinatura.assinar_se_possivel(pdf_minimo(), empresa)
    assert titular is None and not assinatura.esta_assinado(pdf)


def test_tela_de_assinatura_cadastra_e_assina_avulso(cli, empresa):
    assert cli.get(reverse("core:assinaturas")).status_code == 200
    cli.post(reverse("core:assinaturas"), {"acao": "cadastrar", "cert-tipo": "RESPONSAVEL", "cert-senha": SENHA,
                                           "cert-padrao": "on",
                                           "cert-arquivo": SimpleUploadedFile("a1.pfx", pfx_sintetico("RESPONSAVEL:000"))})
    assert CertificadoAssinatura.objects.filter(empresa=empresa, tipo="RESPONSAVEL", padrao=True).exists()
    resposta = cli.post(reverse("core:assinaturas"), {"acao": "assinar", "pdf-arquivo": SimpleUploadedFile("oficio.pdf", pdf_minimo())})
    assert resposta.status_code == 200 and assinatura.esta_assinado(b"".join(resposta.streaming_content))


def test_senha_errada_nao_cadastra(empresa):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        assinatura.cadastrar(empresa, pfx_sintetico(), "errada", "EMPRESA")


def test_relatorio_base_previstas_executadas_e_proximas(empresa, contrato, admin_user):
    from apps.operacao.models import Tarefa
    from apps.operacao.relatorios import novo_relatorio

    contrato.atividades_previstas = "Suporte técnico remoto\n- Manutenção corretiva"
    contrato.save()
    t = Tarefa.objects.create(empresa=empresa, contrato=contrato, titulo="Implantação do sistema", responsavel=admin_user,
                              resumo_para_relatorio="Ambiente configurado.")
    Tarefa.objects.filter(pk=t.pk).update(status="CONCLUIDA", concluida_em=timezone.make_aware(datetime(2026, 10, 8, 10)))
    Tarefa.objects.create(empresa=empresa, contrato=contrato, titulo="Visita presencial", responsavel=admin_user,
                          prazo=date(2026, 11, 5), descricao="Instalação do desktop.")
    rel = novo_relatorio(contrato, date(2026, 10, 1))
    assert "• Suporte técnico remoto" in rel.conteudo and "• Manutenção corretiva" in rel.conteudo
    assert "Implantação do sistema" in rel.conteudo and "Ambiente configurado." in rel.conteudo
    assert "Visita presencial — previsto até 05/11/2026" in rel.consideracoes_finais


def test_previa_relatorio_e_planilha(cli, empresa, contrato, monkeypatch):
    from apps.core import pdf as modulo_pdf
    from apps.financeiro.services import custos
    from apps.operacao import relatorios
    from apps.operacao.relatorios import novo_relatorio

    vistos = []

    def falso(template, ctx):
        vistos.append((template, ctx.get("previa")))
        return pdf_minimo()
    for modulo in (relatorios, custos, modulo_pdf):
        monkeypatch.setattr(modulo, "renderizar_pdf", falso)
    rel = novo_relatorio(contrato, date(2026, 10, 1))
    plan = custos.nova_planilha(contrato, date(2026, 10, 1))
    r1 = cli.get(reverse("fiscal:previa", args=["relatorio", rel.pk]))
    r2 = cli.get(reverse("fiscal:previa", args=["planilha", plan.pk]))
    assert r1["Content-Type"] == "application/pdf" and r2.status_code == 200
    assert vistos == [("pdf/relatorio_atividades.html", True), ("pdf/custos_lrf.html", True)]
    rel.refresh_from_db()
    assert rel.pdf_id is None and rel.status == "RASCUNHO"
    assert "Prévia" in cli.get(reverse("relatorios:home")).content.decode()


@pytest.fixture
def agenda(empresa, contrato):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed

    seed(empresa)
    contrato.vigencia_fim = date(2027, 6, 30)
    contrato.save()
    a = AgendaFaturamento.objects.create(
        empresa=empresa, contrato=contrato, item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
        valor=Decimal("2050"), dia_emissao=5, hora_emissao=time(8), inicio=date(2026, 10, 1), ativa_desde=date(2026, 1, 1),
        referencia="MES_ANTERIOR", tipo_vencimento="PRAZO", prazo_dias=30)
    ciclos.planejar(a, hoje=date(2026, 10, 1), horizonte_dias=150)
    return a


def _ajustar_outubro(agenda, emissao):
    c = CicloFaturamento.objects.get(agenda=agenda, competencia=date(2026, 10, 1))
    return ciclos.ajustar(c, valor=c.valor, data_emissao=emissao, data_vencimento=emissao + timedelta(days=30),
                          discriminacao_texto="")


def emissoes(agenda):
    return {c.competencia.month: c.data_emissao for c in CicloFaturamento.objects.filter(agenda=agenda)}


def test_propagar_emissao_para_dois_meses(agenda):
    antes = emissoes(agenda)
    c = _ajustar_outubro(agenda, date(2026, 10, 22))
    assert ciclos.propagar_emissao(c, "2") == 2
    depois = emissoes(agenda)
    assert depois[10] == date(2026, 10, 22) and depois[11] == date(2026, 11, 22) and depois[12] == date(2026, 12, 22)
    assert depois[1] == antes[1]  # janeiro mantém a regra da agenda
    nov = CicloFaturamento.objects.get(agenda=agenda, competencia=date(2026, 11, 1))
    assert nov.personalizado and nov.data_vencimento == date(2026, 12, 22)


def test_propagar_para_todos_altera_regra_da_agenda(agenda):
    c = _ajustar_outubro(agenda, date(2026, 10, 22))
    ciclos.propagar_emissao(c, "TODOS")
    agenda.refresh_from_db()
    assert agenda.dia_emissao == 22 and agenda.referencia == "MES_CORRENTE"
    assert emissoes(agenda)[1] == date(2027, 1, 22)


def test_ajuste_pela_tela_com_propagacao(cli, agenda):
    c = CicloFaturamento.objects.get(agenda=agenda, competencia=date(2026, 10, 1))
    cli.post(reverse("faturamento:ciclo_acao", args=[c.pk, "ajustar"]), {
        "valor": "2050,00", "data_emissao": "2026-10-22", "data_vencimento": "2026-11-21", "discriminacao": "",
        "propagar": "1"})
    assert emissoes(agenda)[11] == date(2026, 11, 22) and emissoes(agenda)[12] == date(2027, 1, 5)
