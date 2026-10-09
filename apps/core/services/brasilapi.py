"""Consultas públicas: CNPJ (BrasilAPI) e CEP (ViaCEP), com log de integração."""

import httpx

from ..validadores import so_digitos
from .integracao import cronometro, registrar_log

TIMEOUT = httpx.Timeout(10, connect=5)


class ConsultaIndisponivel(Exception):
    pass


def consultar_cnpj(cnpj: str) -> dict:
    cnpj = so_digitos(cnpj)
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    with cronometro() as t:
        try:
            r = httpx.get(url, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            registrar_log("BRASILAPI", "cnpj", request=url, response=str(e), duracao_ms=t())
            raise ConsultaIndisponivel("Serviço de consulta de CNPJ indisponível.") from e
    registrar_log("BRASILAPI", "cnpj", request=url, response=r.text[:5000], status_http=r.status_code,
                  duracao_ms=t(), sucesso=r.status_code == 200)
    if r.status_code == 404:
        raise ConsultaIndisponivel("CNPJ não encontrado na Receita Federal.")
    if r.status_code != 200:
        raise ConsultaIndisponivel(f"Consulta de CNPJ retornou HTTP {r.status_code}.")
    d = r.json()
    return {
        "cpf_cnpj": cnpj,
        "razao_social": d.get("razao_social") or "",
        "nome_fantasia": d.get("nome_fantasia") or "",
        "email": (d.get("email") or "").lower(),
        "telefone": d.get("ddd_telefone_1") or "",
        "optante_simples": bool(d.get("opcao_pelo_simples")),
        "situacao": d.get("descricao_situacao_cadastral") or "",
        "cnae": str(d.get("cnae_fiscal") or ""),
        "natureza_juridica": d.get("natureza_juridica") or "",
        "endereco": {
            "cep": so_digitos(d.get("cep")),
            "tipo_logradouro": d.get("descricao_tipo_de_logradouro") or "",
            "logradouro": d.get("logradouro") or "",
            "numero": d.get("numero") or "S/N",
            "complemento": d.get("complemento") or "",
            "bairro": d.get("bairro") or "",
            "municipio_ibge": str(d.get("codigo_municipio_ibge") or ""),
            "municipio_nome": d.get("municipio") or "",
            "uf": d.get("uf") or "",
        },
    }


def consultar_cep(cep: str) -> dict:
    cep = so_digitos(cep)
    url = f"https://viacep.com.br/ws/{cep}/json/"
    with cronometro() as t:
        try:
            r = httpx.get(url, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            registrar_log("VIACEP", "cep", request=url, response=str(e), duracao_ms=t())
            raise ConsultaIndisponivel("Serviço de CEP indisponível.") from e
    registrar_log("VIACEP", "cep", request=url, response=r.text[:3000], status_http=r.status_code,
                  duracao_ms=t(), sucesso=r.status_code == 200)
    d = r.json() if r.status_code == 200 else {}
    if not d or d.get("erro"):
        raise ConsultaIndisponivel("CEP não encontrado.")
    return {
        "cep": cep,
        "logradouro": d.get("logradouro", ""),
        "complemento": d.get("complemento", ""),
        "bairro": d.get("bairro", ""),
        "municipio_ibge": d.get("ibge", ""),
        "municipio_nome": d.get("localidade", ""),
        "uf": d.get("uf", ""),
    }
