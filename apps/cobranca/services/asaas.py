"""Cliente HTTP da API v3 do Asaas. Toda chamada é registrada em LogIntegracao com segredos mascarados."""

import httpx
from django.core.exceptions import ValidationError

from apps.core.services.integracao import cronometro, registrar_log

URLS = {"SANDBOX": "https://api-sandbox.asaas.com/v3", "PRODUCAO": "https://api.asaas.com/v3"}
TIMEOUT = httpx.Timeout(30, connect=10)


class ErroAsaas(ValidationError):
    pass


class ClienteAsaas:
    def __init__(self, config, transporte=None):
        if not config.api_key_id:
            raise ValidationError("Cadastre a chave de API do Asaas.")
        self.config = config
        self.http = httpx.Client(base_url=URLS[config.ambiente], timeout=TIMEOUT, transport=transporte,
                                 headers={"access_token": config.api_key.ler(), "User-Agent": "KS-CENTRAL/1.0",
                                          "Content-Type": "application/json", "Accept": "application/json"})

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def chamar(self, metodo, caminho, *, json=None, params=None, operacao="", objeto=None):
        with cronometro() as tempo:
            try:
                resposta = self.http.request(metodo, caminho, json=json, params=params)
            except httpx.HTTPError as erro:
                registrar_log("ASAAS", operacao or caminho, objeto=objeto, request=json or params,
                              response=str(erro), duracao_ms=tempo(), empresa=self.config.empresa)
                raise ErroAsaas("Asaas indisponível no momento. Tente novamente em instantes.") from None
            try:
                dados = resposta.json()
            except ValueError:
                dados = {"resposta_nao_json": resposta.text[:500]}
        sucesso = resposta.status_code < 400
        registrar_log("ASAAS", operacao or caminho, objeto=objeto, request=json or params, response=dados,
                      status_http=resposta.status_code, duracao_ms=tempo(), sucesso=sucesso, empresa=self.config.empresa)
        if resposta.status_code == 401:
            raise ErroAsaas("Chave de API do Asaas recusada. Confira a chave e o ambiente.")
        if not sucesso:
            erros = [e.get("description", "") for e in (dados.get("errors") or []) if isinstance(e, dict)]
            raise ErroAsaas("Asaas: " + ("; ".join(e for e in erros if e) or f"HTTP {resposta.status_code}"))
        return dados

    # ---- recursos ----
    def conta(self):
        return self.chamar("GET", "/myAccount/commercialInfo", operacao="conta")

    def buscar_cliente(self, documento):
        dados = self.chamar("GET", "/customers", params={"cpfCnpj": documento, "limit": 1}, operacao="buscar_cliente")
        lista = dados.get("data") or []
        return lista[0] if lista else None

    def criar_cliente(self, corpo, objeto=None):
        return self.chamar("POST", "/customers", json=corpo, operacao="criar_cliente", objeto=objeto)

    def buscar_cobranca_por_referencia(self, referencia):
        dados = self.chamar("GET", "/payments", params={"externalReference": referencia, "limit": 10},
                            operacao="buscar_cobranca")
        validas = [p for p in dados.get("data") or [] if not p.get("deleted")]
        return validas[0] if validas else None

    def criar_cobranca(self, corpo, objeto=None):
        return self.chamar("POST", "/payments", json=corpo, operacao="criar_cobranca", objeto=objeto)

    def cobranca(self, asaas_id):
        return self.chamar("GET", f"/payments/{asaas_id}", operacao="consultar_cobranca")

    def pix(self, asaas_id):
        return self.chamar("GET", f"/payments/{asaas_id}/pixQrCode", operacao="pix_qr")

    def remover(self, asaas_id):
        return self.chamar("DELETE", f"/payments/{asaas_id}", operacao="remover_cobranca")
