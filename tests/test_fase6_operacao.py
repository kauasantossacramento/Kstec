from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.operacao import services
from apps.operacao.models import Tarefa


@pytest.fixture
def tarefa(empresa, contrato, admin_user):
    return Tarefa(empresa=empresa, contrato=contrato, titulo="Suporte de teste", responsavel=admin_user,
                  data_abertura=timezone.localdate() - timedelta(days=1), resumo_para_relatorio="Ajuste realizado e validado.")


def test_ciclo_tarefa_reabertura_auditoria(tarefa, admin_user):
    services.salvar(tarefa, admin_user)
    tarefa = services.transicionar(tarefa, "EM_ANDAMENTO", admin_user)
    tarefa = services.transicionar(tarefa, "EM_REVISAO", admin_user)
    tarefa = services.transicionar(tarefa, "CONCLUIDA", admin_user)
    assert tarefa.concluida_em is not None
    assert tarefa.history.count() == 4
    with pytest.raises(ValidationError, match="Reabra"):
        services.salvar(tarefa, admin_user)
    tarefa = services.transicionar(tarefa, "EM_ANDAMENTO", admin_user)
    assert tarefa.concluida_em is None


def test_conclusao_exige_resumo_e_transicao_valida(tarefa, admin_user):
    tarefa.resumo_para_relatorio = ""
    services.salvar(tarefa, admin_user)
    with pytest.raises(ValidationError, match="situação"):
        services.transicionar(tarefa, "CONCLUIDA", admin_user)
    tarefa = services.transicionar(tarefa, "EM_ANDAMENTO", admin_user)
    with pytest.raises(ValidationError, match="resumo"):
        services.transicionar(tarefa, "CONCLUIDA", admin_user)


def test_horas_limite_diario_entre_tarefas_e_auditoria(tarefa, admin_user):
    services.salvar(tarefa, admin_user)
    apontamento = services.apontar(tarefa, admin_user, timezone.localdate(), Decimal("20"), "Atividade sintética")
    assert apontamento.history.count() == 1
    outra = Tarefa(empresa=tarefa.empresa, titulo="Outra tarefa", responsavel=admin_user)
    services.salvar(outra, admin_user)
    with pytest.raises(ValidationError, match="total"):
        services.apontar(outra, admin_user, timezone.localdate(), Decimal("4.01"), "Excede o dia")
    services.apontar(outra, admin_user, timezone.localdate(), Decimal("4"), "Completa o dia")


@pytest.mark.parametrize("horas", [Decimal("0"), Decimal("-1"), Decimal("24.01"), Decimal("NaN"), Decimal("Infinity"), Decimal("1.001"), 1.1])
def test_horas_invalidas(tarefa, admin_user, horas):
    services.salvar(tarefa, admin_user)
    with pytest.raises(ValidationError):
        services.apontar(tarefa, admin_user, timezone.localdate(), horas, "Teste")
    assert not tarefa.apontamentos.exists()


def test_data_futura_antes_abertura_e_tarefa_encerrada(tarefa, admin_user):
    services.salvar(tarefa, admin_user)
    for data in [timezone.localdate() + timedelta(days=1), tarefa.data_abertura - timedelta(days=1)]:
        with pytest.raises(ValidationError):
            services.apontar(tarefa, admin_user, data, Decimal("1"), "Teste")
    tarefa = services.transicionar(tarefa, "CANCELADA", admin_user)
    with pytest.raises(ValidationError):
        services.apontar(tarefa, admin_user, timezone.localdate(), Decimal("1"), "Teste")


def test_tecnico_somente_alocado_e_leitor_sem_escrita(cli, tarefa, admin_user, leitor, django_user_model):
    services.salvar(tarefa, admin_user)
    tecnico = django_user_model.objects.create_user(email="tecnico@test.local", password="Senha-test-123", empresa=tarefa.empresa)
    tecnico.groups.add(Group.objects.get(name="Operação"))
    assert not services.visiveis(tecnico, tarefa.empresa).exists()
    with pytest.raises(PermissionDenied):
        services.transicionar(tarefa, "EM_ANDAMENTO", tecnico)
    cli.force_login(tecnico)
    assert cli.get(reverse("operacao:tarefa_detalhe", args=[tarefa.pk])).status_code == 404
    tarefa.contrato.responsaveis.add(tecnico)
    assert services.visiveis(tecnico, tarefa.empresa).count() == 1
    assert cli.get(reverse("operacao:tarefa_detalhe", args=[tarefa.pk])).status_code == 200
    assert cli.get(reverse("operacao:kanban")).status_code == 200
    cli.force_login(leitor)
    assert cli.get(reverse("operacao:tarefa_detalhe", args=[tarefa.pk])).status_code == 200
    assert cli.post(reverse("operacao:status", args=[tarefa.pk]), {"status": "CANCELADA"}).status_code == 403


def test_fluxo_http_horas_status_e_aba(cli, tarefa, admin_user):
    services.salvar(tarefa, admin_user)
    assert cli.get(reverse("operacao:tarefa_lista")).status_code == 200
    assert cli.get(reverse("operacao:tarefa_nova")).status_code == 200
    assert cli.get(reverse("contratos:contrato_detalhe", args=[tarefa.contrato_id]) + "?aba=tarefas").status_code == 200
    response = cli.post(reverse("operacao:apontar", args=[tarefa.pk]), {"data": timezone.localdate().isoformat(), "horas": "1,50", "descricao": "Ajustes de teste"})
    assert response.status_code == 302
    assert tarefa.apontamentos.get().horas == Decimal("1.50")
    response = cli.post(reverse("operacao:status", args=[tarefa.pk]), {"status": "EM_ANDAMENTO"})
    assert response.status_code == 302
    tarefa.refresh_from_db()
    assert tarefa.status == "EM_ANDAMENTO"


def test_vinculo_usuario_outra_empresa(tarefa, admin_user, django_user_model):
    from apps.core.models import Empresa
    outra = Empresa.objects.create(cnpj="11222333000181", razao_social="Outra empresa")
    tarefa.responsavel = django_user_model.objects.create_user(email="outra@test.local", empresa=outra)
    with pytest.raises(ValidationError, match="mesma empresa"):
        services.salvar(tarefa, admin_user)


def test_download_evidencia_respeita_alocacao(cli, tarefa, admin_user, django_user_model):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.core.models import Anexo
    services.salvar(tarefa, admin_user)
    anexo = Anexo.de_upload(tarefa, SimpleUploadedFile("teste.txt", b"Evidencia sintetica"))
    tecnico = django_user_model.objects.create_user(email="sem-alocacao@test.local", empresa=tarefa.empresa)
    tecnico.groups.add(Group.objects.get(name="Operação"))
    cli.force_login(tecnico)
    assert cli.get(reverse("core:anexo_baixar", args=[anexo.pk])).status_code == 403
    tarefa.contrato.responsaveis.add(tecnico)
    assert cli.get(reverse("core:anexo_baixar", args=[anexo.pk])).status_code == 200


def test_kanban_contrato_invalido(cli):
    assert cli.get(reverse("operacao:kanban") + "?contrato=invalido").status_code == 400


def test_criacao_http_tarefa(cli, admin_user):
    response = cli.post(reverse("operacao:tarefa_nova"), {
        "titulo": "Tarefa HTTP de teste", "tipo": "SUPORTE", "prioridade": "NORMAL",
        "responsavel": admin_user.pk, "data_abertura": timezone.localdate().isoformat(), "entrar_no_relatorio": "on"})
    assert response.status_code == 302
    obj = Tarefa.objects.get(titulo="Tarefa HTTP de teste")
    assert obj.status == "A_FAZER"
    assert obj.history.get().history_user == admin_user
