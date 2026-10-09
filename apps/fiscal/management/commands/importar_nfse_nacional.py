from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError
from lxml import etree

from apps.core.models import Empresa
from apps.fiscal.models import ConfiguracaoFiscal
from apps.fiscal.services.configuracao import carregar_a1
from apps.fiscal.services.emissao import nacional_url
from apps.fiscal.services.homologacao import NS
from apps.fiscal.services.importacao import importar_confirmada


class Command(BaseCommand):
    help = "Importa XML nacional após confirmar a chave pela API autenticada. Não emite notas."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--cnpj", required=True)
        parser.add_argument("--canal", required=True, choices=ConfiguracaoFiscal.Canal.values)

    def handle(self, *args, **options):
        empresa = Empresa.objects.get(cnpj=options["cnpj"])
        config = ConfiguracaoFiscal.objects.get(empresa=empresa)
        xml = Path(options["arquivo"]).read_bytes()
        if len(xml) > 5_000_000:
            raise CommandError("XML acima de 5 MB.")
        doc = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
        chave = doc.find(f"{{{NS}}}infNFSe").get("Id")[3:]
        ambiente = int(doc.findtext(f".//{{{NS}}}DPS/{{{NS}}}infDPS/{{{NS}}}tpAmb"))
        with httpx.Client(verify=carregar_a1(config).contexto_tls(), timeout=45, follow_redirects=False) as cliente:
            resposta = cliente.get(f"{nacional_url(ambiente)}/nfse/{chave}")
            if resposta.status_code != 200:
                raise CommandError("Consulta nacional não confirmou o documento; nenhuma nota importada.")
            nota, criada = importar_confirmada(empresa, xml, resposta.json(), options["canal"])
        self.stdout.write(f"NFS-e {nota.numero_nfse}: {'importada' if criada else 'já cadastrada'}; ID {nota.pk}.")
