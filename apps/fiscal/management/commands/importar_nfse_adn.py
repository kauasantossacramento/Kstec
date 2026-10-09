"""Sincroniza as NFS-e emitidas pelo CNPJ (inclusive fora do sistema) a partir da distribuição nacional (ADN).

Somente consultas GET autenticadas com o A1. Não emite, não cancela, não altera a sequência de DPS.
Notas com evento de cancelamento (inclusive por substituição) entram como CANCELADA, sem recebível.

    python manage.py importar_nfse_adn --desde 2026-01-01          # importa
    python manage.py importar_nfse_adn --desde 2026-01-01 --simular # só lista
"""

import base64
import gzip
from datetime import date

import httpx
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from lxml import etree

from apps.core import contexto
from apps.core.models import Empresa, Parametro
from apps.core.services.integracao import registrar_log
from apps.fiscal.models import ConfiguracaoFiscal
from apps.fiscal.services.configuracao import carregar_a1
from apps.fiscal.services.homologacao import NS
from apps.fiscal.services.importacao import importar_historica

URL = "https://adn.nfse.gov.br/contribuintes/DFe/{nsu}?cnpjConsulta={cnpj}&lote=true"
CHAVE_NSU = "fiscal.adn_ultimo_nsu"


class Command(BaseCommand):
    help = "Importa NFS-e emitidas pela empresa a partir da distribuição nacional (ADN). Não emite notas."

    def add_arguments(self, parser):
        parser.add_argument("--desde", default="", help="Ignora notas processadas antes desta data (AAAA-MM-DD).")
        parser.add_argument("--nsu", type=int, default=None, help="NSU inicial (padrão: continua da última leitura).")
        parser.add_argument("--simular", action="store_true", help="Lista sem gravar.")
        parser.add_argument("--ignorar", action="append", default=[], help="Número de NFS-e a não importar (repetível).")

    def handle(self, *args, **opts):
        empresa = Empresa.objects.order_by("criado_em").first()
        config = ConfiguracaoFiscal.objects.filter(empresa=empresa).first()
        if config is None:
            raise CommandError("Cadastre a configuração fiscal com o A1.")
        desde = date.fromisoformat(opts["desde"]) if opts["desde"] else None
        nsu = opts["nsu"] if opts["nsu"] is not None else int(Parametro.get(CHAVE_NSU, 0, empresa=empresa) or 0)
        documentos, cancelamentos = [], set()
        with contexto.usar_contexto(empresa), httpx.Client(verify=carregar_a1(config).contexto_tls(), timeout=60) as cli:
            for _ in range(200):
                resposta = cli.get(URL.format(nsu=nsu, cnpj=empresa.cnpj))
                dados = resposta.json() if resposta.headers.get("content-type", "").startswith("application/json") else {}
                lote = dados.get("LoteDFe") or []
                registrar_log("ADN", "distribuicao_dfe", response={"nsu": nsu, "status": dados.get("StatusProcessamento"),
                              "itens": len(lote)}, status_http=resposta.status_code, sucesso=resposta.status_code in (200, 404),
                              empresa=empresa)
                if resposta.status_code != 200 or not lote:
                    break
                for item in lote:
                    xml = gzip.decompress(base64.b64decode(item["ArquivoXml"]))
                    if item.get("TipoDocumento") == "EVENTO" and "CANCELAMENTO" in (item.get("TipoEvento") or ""):
                        cancelamentos.add(item["ChaveAcesso"])
                    elif item.get("TipoDocumento") == "NFSE":
                        documentos.append(xml)
                nsu = max(i["NSU"] for i in lote)
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            novas = 0
            for xml in documentos:
                doc = etree.fromstring(xml, parser)
                inf = doc.find(f"{{{NS}}}infNFSe")
                dps = inf.find(f"{{{NS}}}DPS/{{{NS}}}infDPS")
                if dps.findtext(f"{{{NS}}}prest/{{{NS}}}CNPJ") != empresa.cnpj:
                    continue  # notas recebidas (empresa como tomadora) ficam fora
                processada = inf.findtext(f"{{{NS}}}dhProc")[:10]
                if desde and date.fromisoformat(processada) < desde:
                    continue
                if inf.findtext(f"{{{NS}}}nNFSe") in opts["ignorar"]:
                    continue
                chave = inf.get("Id")[3:]
                cancelada = chave in cancelamentos
                rotulo = (f"NFS-e {inf.findtext(f'{{{NS}}}nNFSe')} · {processada} · "
                          f"{dps.findtext(f'{{{NS}}}valores/{{{NS}}}vServPrest/{{{NS}}}vServ')} · "
                          f"{'CANCELADA' if cancelada else 'válida'}")
                if opts["simular"]:
                    self.stdout.write(rotulo)
                    continue
                try:
                    nota, criada = importar_historica(empresa, xml, cancelada=cancelada)
                except ValidationError as erro:
                    self.stderr.write(f"{rotulo}: {'; '.join(erro.messages)}")
                    continue
                novas += int(criada)
                self.stdout.write(f"{rotulo}: {'importada' if criada else 'já cadastrada'}")
            if not opts["simular"]:
                Parametro.definir(CHAVE_NSU, nsu, "Último NSU lido da distribuição nacional (ADN).", empresa=empresa)
        self.stdout.write(self.style.SUCCESS(f"{len(documentos)} documento(s) lido(s); {novas} nova(s) nota(s)."))
