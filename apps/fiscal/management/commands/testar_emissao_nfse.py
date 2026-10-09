import getpass
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Empresa
from apps.fiscal.certificado import CertificadoA1
from apps.fiscal.services.homologacao import URL, corpo_envio, preparar_dps


class Command(BaseCommand):
    help = "Prepara DPS assinada/XSD de R$ 1,00. --enviar-homologacao envia só à produção restrita."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--enviar-homologacao", action="store_true")

    def handle(self, *args, **options):
        empresa = Empresa.objects.order_by("criado_em").first()
        if empresa is None:
            raise CommandError("Cadastre a empresa.")
        senha = os.environ.get("KSCENTRAL_A1_SENHA") or getpass.getpass("Senha do A1: ")
        a1 = CertificadoA1(options["arquivo"], senha, empresa.cnpj)
        numero = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        identificador, xml = preparar_dps(a1, numero, empresa.municipio_ibge)
        pasta = Path(".tools/emissoes-homologacao") / identificador
        pasta.mkdir(parents=True, exist_ok=False)
        (pasta / "dps-assinada.xml").write_bytes(xml)
        self.stdout.write(f"DPS {identificador}: assinatura e XSD válidos; valor R$ 1,00; ambiente 2.")
        if not options["enviar_homologacao"]:
            return
        estado = {"id_dps": identificador, "ambiente": "PRODUCAO_RESTRITA", "valor": "1.00", "situacao": "PREPARADA"}
        destino = pasta / "resultado.json"

        def gravar():
            destino.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")

        gravar()
        with httpx.Client(verify=a1.contexto_tls(), timeout=httpx.Timeout(60, connect=15), follow_redirects=False) as cliente:
            try:
                existente = cliente.get(f"{URL}/dps/{identificador}")
            except httpx.HTTPError as erro:
                estado["situacao"] = "NAO_ENVIADA_CONSULTA_PREVIA"
                estado["erro"] = type(erro).__name__
                gravar()
                raise CommandError("Falha na consulta prévia; nenhuma emissão enviada.") from erro
            estado["consulta_antes_http"] = existente.status_code
            if existente.status_code != 404:
                estado["situacao"] = "NAO_ENVIADA_CONSULTA_PREVIA"
                estado["consulta_antes"] = existente.text
                gravar()
                raise CommandError("Consulta prévia não confirmou ausência da DPS; envio bloqueado.")
            estado["situacao"] = "ENVIO_INICIADO"
            gravar()
            try:
                resposta = cliente.post(f"{URL}/nfse", json=corpo_envio(xml))
            except httpx.HTTPError as erro:
                estado["situacao"] = "INDETERMINADA_NAO_RETRANSMITIR"
                estado["erro"] = type(erro).__name__
                gravar()
                try:
                    consulta = cliente.get(f"{URL}/dps/{identificador}")
                    estado["consulta_apos_http"] = consulta.status_code
                    estado["consulta_apos"] = consulta.text
                except httpx.HTTPError as erro_consulta:
                    estado["erro_consulta_apos"] = type(erro_consulta).__name__
                finally:
                    gravar()
                raise CommandError("Envio sem confirmação. Consulte a DPS antes de qualquer nova tentativa.") from erro
            estado["http"] = resposta.status_code
            try:
                estado["retorno"] = resposta.json()
            except ValueError:
                estado["retorno"] = resposta.text
            estado["situacao"] = "AUTORIZADA_HOMOLOGACAO" if resposta.status_code == 201 else "REJEITADA" if resposta.status_code in (400, 403, 422) else "INDETERMINADA_NAO_RETRANSMITIR"
            gravar()
            self.stdout.write(json.dumps({k: v for k, v in estado.items() if k != "retorno"}, ensure_ascii=False))
            if isinstance(estado["retorno"], dict):
                self.stdout.write(json.dumps({k: v for k, v in estado["retorno"].items() if "xml" not in k.lower()}, ensure_ascii=False))
            self.stdout.write(f"Resposta completa preservada em {destino}.")
