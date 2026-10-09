import getpass
import json
import os
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.fiscal.services.el_nacional import ClienteMunicipalEL, interpretar_retorno


class Command(BaseCommand):
    help = "Consulta processamento da DPS no novo canal municipal E&L. Não emite documentos."

    def add_arguments(self, parser):
        parser.add_argument("id_dps")
        parser.add_argument("--ambiente", type=int, choices=[1, 2], default=2)

    def handle(self, *args, **options):
        token = os.environ.get("KSCENTRAL_EL_TOKEN") or getpass.getpass("Token de integração E&L: ")
        cliente = ClienteMunicipalEL(token)
        try:
            status, retorno = cliente.consultar(options["id_dps"], options["ambiente"])
        except ValidationError as erro:
            raise CommandError("; ".join(erro.messages)) from None
        finally:
            cliente.close()
        situacao = interpretar_retorno(status, retorno, options["id_dps"], options["ambiente"], consulta=True)
        destino = Path(".tools/emissoes-producao") / options["id_dps"] / "resultado.json"
        if options["ambiente"] == 1 and destino.exists():
            estado = json.loads(destino.read_text(encoding="utf-8"))
            municipal = estado.get("canais", {}).get("municipal")
            if municipal:
                municipal.setdefault("consultas", []).append({"http": status, "retorno": retorno, "situacao": situacao})
                municipal["resultado_consulta"] = situacao
                # Nunca libera outro POST após o recebimento municipal de uma DPS.
                if situacao == "XML_NFSE_DISPONIVEL_VALIDACAO_PENDENTE":
                    municipal["situacao"] = situacao
                temporario = destino.with_suffix(".tmp")
                temporario.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
                temporario.replace(destino)
        self.stdout.write(json.dumps({"http": status, "situacao": interpretar_retorno(
            status, retorno, options["id_dps"], options["ambiente"], consulta=True),
            "erros": retorno.get("erros", []) if isinstance(retorno, dict) else []}, ensure_ascii=False))
