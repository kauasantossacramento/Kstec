"""Massa sintética de R$ 1,00 somente no endpoint municipal de homologação."""
import getpass
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.cadastros.models import Pessoa
from apps.core.models import Empresa
from apps.fiscal.certificado import CertificadoA1
from apps.fiscal.services.el_nacional import SCHEMAS_EL, ClienteMunicipalEL, interpretar_retorno
from apps.fiscal.services.homologacao import preparar_dps


class Command(BaseCommand):
    help = "DPS municipal de teste, classificação do exemplo E&L e tributação sintética. Nunca emite em produção."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--tomador", required=True)
        parser.add_argument("--enviar-homologacao", action="store_true")
        parser.add_argument("--codigo-municipal-teste", default="101")

    def handle(self, *args, **options):
        empresa = Empresa.objects.filter(cnpj="62501281000113", municipio_ibge="2932903").first()
        if not empresa or not empresa.inscricao_municipal:
            raise CommandError("Cadastre a empresa de Valença/BA com inscrição municipal.")
        pessoa = Pessoa.objects.filter(empresa=empresa, cpf_cnpj=options["tomador"], tipo="F").first()
        if not pessoa:
            raise CommandError("Cadastre o tomador pessoa física.")
        senha = os.environ.get("KSCENTRAL_A1_SENHA") or getpass.getpass("Senha do A1: ")
        a1 = CertificadoA1(options["arquivo"], senha, empresa.cnpj)
        identificador, xml = preparar_dps(
            a1, datetime.now(UTC).strftime("%Y%m%d%H%M%S"), empresa.municipio_ibge,
            inscricao_municipal=empresa.inscricao_municipal,
            tomador={"cpf": pessoa.cpf_cnpj, "nome": pessoa.razao_social},
            codigo_municipal=options["codigo_municipal_teste"], codigo_nacional="010101", nbs="115021000",
            schemas=SCHEMAS_EL, aliquota_iss_teste="2.00")
        pasta = Path(".tools/emissoes-el-homologacao") / identificador
        pasta.mkdir(parents=True, exist_ok=False)
        (pasta / "dps-assinada.xml").write_bytes(xml)
        estado = {"id_dps": identificador, "ambiente": 2, "valor": "1.00", "situacao": "PREPARADA",
                  "massa_sintetica": True, "aliquota_iss_teste": "2.00",
                  "codigo_municipal_teste": options["codigo_municipal_teste"]}

        def gravar():
            (pasta / "resultado.json").write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")

        gravar()
        self.stdout.write(f"DPS assinada e XSD municipal válidos: {identificador}; homologação R$ 1,00.")
        if not options["enviar_homologacao"]:
            return
        token = os.environ.get("KSCENTRAL_EL_TOKEN") or getpass.getpass("Token E&L: ")
        cliente = ClienteMunicipalEL(token)
        try:
            estado["situacao"] = "TENTATIVA_INICIADA"
            gravar()
            status, retorno = cliente.enviar_homologacao(xml, a1)
            estado.update(http=status, retorno=retorno, situacao=interpretar_retorno(status, retorno, identificador, 2))
            gravar()
            # Apenas uma consulta após recebimento; não repete POST.
            if estado["situacao"] == "EM_PROCESSAMENTO":
                status_consulta, consulta = cliente.consultar(identificador)
                estado.update(consulta_http=status_consulta, consulta=consulta,
                              situacao=interpretar_retorno(status_consulta, consulta, identificador, 2))
                gravar()
        except ValidationError as erro:
            estado.update(situacao="INDETERMINADA_NAO_RETRANSMITIR", erro=erro.messages)
            gravar()
            raise CommandError("; ".join(erro.messages)) from None
        finally:
            cliente.close()
        self.stdout.write(json.dumps({k: v for k, v in estado.items() if k not in ("retorno", "consulta")}, ensure_ascii=False))
        self.stdout.write(json.dumps(retorno.get("erros", []), ensure_ascii=False))
        self.stdout.write(f"Evidências: {pasta}")
