"""Diagnóstico somente GET. Nenhuma autorização fiscal é solicitada."""
import getpass
import json
import os
from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError
from lxml import etree

from apps.core.models import Empresa
from apps.fiscal.certificado import CertificadoA1

BASES = {
    "restrita": "https://sefin.producaorestrita.nfse.gov.br/API/SefinNacional",
    "producao": "https://sefin.nfse.gov.br/SefinNacional",
}


class Command(BaseCommand):
    help = "Valida A1 e testa acesso GET às documentações oficiais, sem emitir notas."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--saida", default=".tools/diagnostico-nfse.json")

    def handle(self, *args, **options):
        empresa = Empresa.objects.order_by("criado_em").first()
        if empresa is None:
            raise CommandError("Cadastre a empresa prestadora.")
        senha = os.environ.get("KSCENTRAL_A1_SENHA") or getpass.getpass("Senha do A1: ")
        a1 = CertificadoA1(options["arquivo"], senha, empresa.cnpj)
        relatorio = {"certificado": a1.metadados(), "testes": []}
        consultas = [(ambiente, f"{base}/docs/index", "documentacao") for ambiente, base in BASES.items()]
        for ambiente, host in [("restrita", "adn.producaorestrita.nfse.gov.br"), ("producao", "adn.nfse.gov.br")]:
            consultas.append((ambiente, f"https://{host}/parametrizacao/{empresa.municipio_ibge}/convenio", "convenio"))
        if empresa.municipio_ibge == "2932903":
            consultas.append(("municipal_producao", "https://ba-valenca-pm-nfs-backend.cloud.el.com.br/producao/NfseWSService?wsdl", "wsdl"))
        with httpx.Client(verify=a1.contexto_tls(), timeout=httpx.Timeout(30, connect=15), follow_redirects=False) as cliente:
            for ambiente, url, tipo in consultas:
                try:
                    resposta = cliente.get(url)
                    entrada = {"ambiente": ambiente, "tipo": tipo, "url": url, "status_http": resposta.status_code}
                    if resposta.status_code == 200 and tipo == "documentacao":
                        pagina = Path(options["saida"]).parent / f"swagger-{ambiente}.html"
                        pagina.parent.mkdir(parents=True, exist_ok=True)
                        pagina.write_text(resposta.text, encoding="utf-8")
                    if tipo == "convenio":
                        try:
                            entrada["retorno"] = resposta.json()
                        except ValueError:
                            entrada["retorno"] = "Resposta não JSON; consulte HTTP e tipo de conteúdo."
                    if tipo == "wsdl" and resposta.status_code == 200:
                        raiz = etree.fromstring(resposta.content, etree.XMLParser(resolve_entities=False, no_network=True))
                        entrada["operacoes"] = raiz.xpath('//*[local-name()="portType"]/*[local-name()="operation"]/@name')
                        entrada["endpoints"] = raiz.xpath('//*[local-name()="address"]/@location')
                    entrada["tipo_conteudo"] = resposta.headers.get("content-type", "")
                except httpx.HTTPError as erro:
                    entrada = {"ambiente": ambiente, "url": url, "erro": type(erro).__name__, "detalhe": str(erro)}
                relatorio["testes"].append(entrada)
                self.stdout.write(json.dumps(entrada, ensure_ascii=False))
        destino = Path(options["saida"])
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"Diagnóstico salvo em {destino}; nenhuma emissão solicitada.")
