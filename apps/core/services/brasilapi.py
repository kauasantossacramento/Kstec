"""Consultas públicas: CNPJ (BrasilAPI) e CEP (ViaCEP), com log de integração."""

import httpx

from ..validadores import cnpj_valido, so_digitos
from .integracao import cronometro, registrar_log

TIMEOUT = httpx.Timeout(10, connect=5)


class ConsultaIndisponivel(Exception):
    pass


def consultar_cnpj(cnpj: str) -> dict:
    cnpj = so_digitos(cnpj)
    if not cnpj_valido(cnpj):
        raise ConsultaIndisponivel("Informe um CNPJ válido com 14 dígitos.")
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    with cronometro() as t:
        try:
            r = httpx.get(url, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            registrar_log("BRASILAPI", "cnpj", request=url, response=str(e), duracao_ms=t())
            raise ConsultaIndisponivel("Serviço de consulta de CNPJ indisponível.") from e
    registrar_log("BRASILAPI", "cnpj", request=url,
                  response="Dados cadastrais recebidos." if r.status_code == 200 else r.text[:1000], status_http=r.status_code,
                  duracao_ms=t(), sucesso=r.status_code == 200)
    if r.status_code == 404:
        raise ConsultaIndisponivel("CNPJ não encontrado na Receita Federal.")
    if r.status_code != 200:
        raise ConsultaIndisponivel("BrasilAPI indisponível no momento. Tente novamente ou preencha os dados manualmente.")
    try:
        d = r.json()
    except ValueError as e:
        raise ConsultaIndisponivel("O serviço de CNPJ retornou uma resposta inválida. Tente novamente.") from e
    if not isinstance(d, dict) or not d.get("razao_social"):
        raise ConsultaIndisponivel("O serviço de CNPJ retornou dados incompletos. Tente novamente.")
    return {
        "cpf_cnpj": cnpj,
        "razao_social": d.get("razao_social") or "",
        "nome_fantasia": d.get("nome_fantasia") or "",
        "email": (d.get("email") or "").lower(),
        "telefone": d.get("ddd_telefone_1") or "",
        "optante_simples": d.get("opcao_pelo_simples") if isinstance(d.get("opcao_pelo_simples"), bool) else None,
        "situacao": d.get("descricao_situacao_cadastral") or "",
        "situacao_cadastral": d.get("descricao_situacao_cadastral") or "",
        "data_abertura": d.get("data_inicio_atividade") or "",
        "cnae": str(d.get("cnae_fiscal") or ""),
        "cnae_principal": str(d.get("cnae_fiscal") or ""),
        "descricao_cnae": d.get("cnae_fiscal_descricao") or "",
        "natureza_juridica": d.get("natureza_juridica") or "",
        "porte": d.get("porte") or "",
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
