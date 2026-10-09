import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from django.core import mail
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.certidoes import services as cert_services
from apps.certidoes.models import Certidao, KitHabilitacao, TipoCertidao
from apps.certidoes.seeds import seed as seed_certidoes
from apps.contratos.models import Aditivo, Competencia
from apps.contratos.services import alertas_contrato, gerar_competencias
from apps.core.agenda import itens_atencao


def test_saldo_com_aditivo(contrato):
    Aditivo.objects.create(contrato=contrato, numero="1", tipo="PRAZO_VALOR", data=date(2026, 6, 1),
                           nova_vigencia_fim=date(2027, 6, 30), valor_acrescimo=Decimal("15000.00"))
    assert contrato.valor_atualizado == Decimal("75000.00")
    assert contrato.saldo == Decimal("75000.00")
    assert contrato.vigencia_fim_atual == date(2027, 6, 30)


def test_gerar_competencias_idempotente(contrato):
    assert gerar_competencias(contrato) == 12
    assert gerar_competencias(contrato) == 0
    assert Competencia.objects.filter(contrato=contrato).first().ano_mes == date(2026, 1, 1)


@freeze_time("2026-12-10 15:00")
def test_alerta_vigencia_30_dias(contrato):
    alertas = alertas_contrato(contrato)
    assert any(a["nivel"] == "danger" and "21 dias" in a["texto"] for a in alertas)


def test_hub_contrato_abas(cli, contrato):
    for aba in ["resumo", "notas", "historico", "documentos", "custos"]:
        r = cli.get(reverse("contratos:contrato_detalhe", args=[contrato.pk]) + f"?aba={aba}")
        assert r.status_code == 200, aba
    assert cli.get(reverse("contratos:contrato_lista")).status_code == 200
    assert cli.get(reverse("contratos:contrato_novo")).status_code == 200


def test_operacao_ve_apenas_contratos_alocados(client, empresa, contrato, django_user_model):
    from django.contrib.auth.models import Group

    tec = django_user_model.objects.create_user(email="tec@kstec.online", password="x" * 12, empresa=empresa)
    tec.groups.add(Group.objects.get(name="Operação"))
    client.force_login(tec)
    assert client.get(reverse("contratos:contrato_detalhe", args=[contrato.pk])).status_code == 404
    contrato.responsaveis.add(tec)
    assert client.get(reverse("contratos:contrato_detalhe", args=[contrato.pk])).status_code == 200


def test_extracao_dados_certidao():
    texto = ("CERTIDÃO NEGATIVA DE DÉBITOS RELATIVOS AOS TRIBUTOS FEDERAIS\n"
             "Emitida às 10:21:33 do dia 02/09/2026 <hora e data de Brasília>.\n"
             "Válida até 01/03/2027.\nCódigo de controle da certidão: 1A2B.3C4D.5E6F.7G8H")
    d = cert_services.extrair_dados(texto)
    assert d["data_validade"] == date(2027, 3, 1)
    assert d["data_emissao"] == date(2026, 9, 2)
    assert d["numero"] == "1A2B.3C4D.5E6F.7G8H"
    assert d["situacao"] == "NEGATIVA"


def test_certidao_vencendo_aparece_no_painel_e_gera_email(empresa, admin_user, cli):
    seed_certidoes(empresa)
    tipo = TipoCertidao.objects.get(nome__startswith="CNDT")
    hoje = timezone.localdate()
    Certidao.objects.create(tipo=tipo, data_emissao=hoje - timedelta(days=170), data_validade=hoje + timedelta(days=7))
    itens = itens_atencao(empresa, admin_user)
    assert any("CNDT" in i.titulo and "vencendo" in i.titulo for i in itens)
    assert cert_services.alertar_vencimentos() >= 1
    assert any("CNDT" in m.subject for m in mail.outbox)
    assert "CNDT" in cli.get(reverse("painel:home")).content.decode()
    situ = cert_services.situacao_habilitacao(empresa)
    assert situ["geral"] == "INAPTA"  # demais obrigatórias ausentes


def test_kit_zip(empresa, cli):
    seed_certidoes(empresa)
    hoje = timezone.localdate()
    t1, t2 = TipoCertidao.objects.all()[:2]
    c1 = Certidao.objects.create(tipo=t1, data_emissao=hoje, data_validade=hoje + timedelta(days=90))
    c1.arquivo.save("c1.pdf", io.BytesIO(b"%PDF-1.4 teste"), save=True)
    c2 = Certidao.objects.create(tipo=t2, data_emissao=hoje - timedelta(days=100), data_validade=hoje - timedelta(days=1))
    kit = KitHabilitacao.objects.create(nome="Dispensa 012/2026")
    kit.certidoes.set([c1, c2])
    r = cli.post(reverse("certidoes:kit_gerar", args=[kit.pk]))
    assert r.status_code == 302
    kit.refresh_from_db()
    nomes = zipfile.ZipFile(io.BytesIO(kit.zip.ler())).namelist()
    assert "00_indice.pdf" in nomes and len(nomes) == 2  # vencida fica de fora


def test_paginas_certidoes_e_agenda(cli, empresa, contrato):
    seed_certidoes(empresa)
    for nome in ["certidoes:home", "certidoes:certidao_lista", "certidoes:certidao_nova", "certidoes:kit_lista",
                 "certidoes:tipo_lista", "painel:agenda"]:
        assert cli.get(reverse(nome)).status_code == 200, nome
    r = cli.get(reverse("painel:agenda") + "?dias=365")
    assert "Fim de vigência" in r.content.decode()
