import getpass
import json
import os
from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError
from lxml import etree

from apps.core.models import Empresa
from apps.fiscal.certificado import CertificadoA1
from apps.fiscal.services.municipal import URL_VALENCA, consulta_rps, mensagens_resposta


class Command(BaseCommand):
    help = "Consulta RPS municipal por número e série. Não cria/cancela documentos fiscais."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("numero")
        parser.add_argument("serie")

    def handle(self, *args, **options):
        empresa = Empresa.objects.order_by("criado_em").first()
        if empresa is None or empresa.municipio_ibge != "2932903":
            raise CommandError("Esta consulta atende exclusivamente Valença/BA.")
        senha = os.environ.get("KSCENTRAL_A1_SENHA") or getpass.getpass("Senha do A1: ")
        a1 = CertificadoA1(options["arquivo"], senha, empresa.cnpj)
        xml = consulta_rps(empresa.cnpj, options["numero"], options["serie"], empresa.inscricao_municipal)
        pasta = Path(".tools/consulta-municipal")
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "requisicao.xml").write_bytes(xml)
        with httpx.Client(verify=a1.contexto_tls(), timeout=45, follow_redirects=False) as cliente:
            resposta = cliente.post(URL_VALENCA, content=xml, headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'})
        (pasta / "resposta.xml").write_bytes(resposta.content)
        self.stdout.write(f"HTTP {resposta.status_code}; resposta salva em {pasta}.")
        try:
            self.stdout.write(json.dumps(mensagens_resposta(resposta.content), ensure_ascii=False))
        except etree.XMLSyntaxError:
            self.stdout.write("Resposta sem XML reconhecível; consultar o arquivo salvo.")
