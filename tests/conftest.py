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
