import pytest
from django.conf import settings


@pytest.mark.django_db
def test_health_responde(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["componentes"]["banco"]["status"] == "ok"


def test_configuracao_regional():
    assert settings.TIME_ZONE == "America/Bahia"
    assert settings.LANGUAGE_CODE == "pt-br"
    assert settings.USE_THOUSAND_SEPARATOR is True
