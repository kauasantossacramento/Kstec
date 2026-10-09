import pytest
from django.contrib.auth.models import Group

from apps.core import contexto
from apps.core.seeds import seed as seed_core


@pytest.fixture
def empresa(db):
    emp = seed_core()
    tokens = contexto.definir(emp, None)
    yield emp
    contexto.limpar(tokens)


@pytest.fixture
def admin_user(empresa, django_user_model):
    u = django_user_model.objects.create_user(email="admin@kstec.online", password="Senha-forte-123",
                                              nome="Kauã Admin", empresa=empresa)
    u.groups.add(Group.objects.get(name="Administrador"))
    return u


@pytest.fixture
def leitor(empresa, django_user_model):
    u = django_user_model.objects.create_user(email="contador@externo.com", password="Senha-forte-123",
                                              nome="Contador", empresa=empresa)
    u.groups.add(Group.objects.get(name="Leitura"))
    return u


@pytest.fixture
def cli(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture
def pessoa(empresa):
    from apps.cadastros.models import Pessoa
    from apps.core.models import Endereco

    end = Endereco.objects.create(cep="45400000", logradouro="Praça da República", numero="10", bairro="Centro",
                                  municipio_ibge="2932903", municipio_nome="Valença", uf="BA")
    return Pessoa.objects.create(cpf_cnpj="13927819000140", razao_social="MUNICIPIO DE VALENCA",
                                 e_orgao_publico=True, esfera="MUNICIPAL", endereco=end,
                                 email="financas@valenca.ba.gov.br")


@pytest.fixture
def contrato(empresa, pessoa):
    from datetime import date
    from decimal import Decimal

    from apps.contratos.models import Contrato

    return Contrato.objects.create(
        numero="012/2026", objeto="Manutenção e suporte do sistema de protocolo", cliente=pessoa,
        data_assinatura=date(2026, 1, 5), vigencia_inicio=date(2026, 1, 1), vigencia_fim=date(2026, 12, 31),
        valor_global=Decimal("60000.00"), valor_mensal=Decimal("5000.00"),
        discriminacao_padrao="Serviços de suporte — competência {competencia} — contrato {contrato}",
    )
