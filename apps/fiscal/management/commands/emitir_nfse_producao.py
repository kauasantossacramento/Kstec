"""Emissão explícita por canal, sem repetição automática de POST."""
import getpass
import json
import os
from pathlib import Path

import httpx
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.cadastros.models import Pessoa
from apps.catalogo.models import ItemCatalogo
from apps.core.models import Empresa
from apps.fiscal.certificado import CertificadoA1
from apps.fiscal.services.el_nacional import SCHEMAS_EL, ClienteMunicipalEL, dps_ausente, interpretar_retorno
from apps.fiscal.services.producao import URL, corpo_producao, preparar_dps_producao


class Command(BaseCommand):
    help = "Prepara DPS real do Simples; --enviar-producao transmite uma única vez no canal escolhido."

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--numero", required=True)
        parser.add_argument("--canal", choices=("nacional", "municipal"), required=True)
        parser.add_argument("--tomador", required=True)
        parser.add_argument("--item", required=True)
        parser.add_argument("--codigo-municipal", required=True)
        parser.add_argument("--valor", required=True)
        parser.add_argument("--iss", required=True)
        parser.add_argument("--tributos-simples", required=True)
        parser.add_argument("--enviar-producao", action="store_true")

    def handle(self, *args, **options):
        empresa = Empresa.objects.filter(cnpj="62501281000113", municipio_ibge="2932903").first()
        if not empresa or empresa.regime_tributario != "SIMPLES":
            raise CommandError("Este fluxo exige o cadastro da empresa de Valença como optante do Simples.")
        pessoa = Pessoa.objects.filter(empresa=empresa, cpf_cnpj=options["tomador"], tipo="F").first()
        item = ItemCatalogo.objects.select_related("nbs", "codigo_tributacao_nacional").filter(
            empresa=empresa, codigo_interno=options["item"], natureza="SERVICO").first()
        if not pessoa or not item or not item.nbs or not item.codigo_tributacao_nacional or not item.codigo_tributacao_nacional.vigente:
            raise CommandError("Cadastre tomador e serviço com NBS e código nacional vigente.")
        senha = os.environ.get("KSCENTRAL_A1_SENHA") or getpass.getpass("Senha do A1: ")
        a1 = CertificadoA1(options["arquivo"], senha, empresa.cnpj)
        parametros = dict(municipio=empresa.municipio_ibge, inscricao_municipal=empresa.inscricao_municipal,
                          tomador={"cpf": pessoa.cpf_cnpj, "nome": pessoa.razao_social},
                          codigo_nacional=item.codigo_tributacao_nacional.codigo, nbs=item.nbs.codigo,
                          codigo_municipal=options["codigo_municipal"], descricao=item.nome,
                          valor=options["valor"], aliquota_iss=options["iss"],
                          total_tributos_simples=options["tributos_simples"])
        identificador, xml = preparar_dps_producao(a1, options["numero"], **parametros)
        pasta = Path(".tools/emissoes-producao") / identificador
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / "resultado.json"
        if destino.exists():
            estado = json.loads(destino.read_text(encoding="utf-8"))
            if estado["parametros"] != parametros:
                raise CommandError("DPS já preparada com outros parâmetros; alteração bloqueada.")
            xml = (pasta / "dps-assinada.xml").read_bytes()
        else:
            estado = {"id_dps": identificador, "ambiente": 1, "parametros": parametros, "canais": {}}
            (pasta / "dps-assinada.xml").write_bytes(xml)

        def gravar():
            temporario = destino.with_suffix(".tmp")
            temporario.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
            temporario.replace(destino)

        canal = options["canal"]
        corpo = corpo_producao(xml, a1, SCHEMAS_EL) if canal == "municipal" else corpo_producao(xml, a1)
        if not destino.exists():
            gravar()
        self.stdout.write(f"DPS {identificador}: produção, assinatura e XSD válidos; R$ {options['valor']}.")
        if not options["enviar_producao"]:
            return
        if canal in estado["canais"]:
            raise CommandError("Canal já registrado para esta DPS; consulte o resultado, não repita o envio.")
        if any(registro.get("situacao") != "REJEITADA" for registro in estado["canais"].values()):
            raise CommandError("Outro canal está pendente ou recebeu a DPS; nova emissão bloqueada.")
        # Exclusão entre processos desde a consulta prévia até a persistência do POST.
        trava = pasta / "envio.lock"
        try:
            trava.open("x").close()
        except FileExistsError:
            raise CommandError("Existe uma tentativa em andamento; consulte a DPS.") from None
        cliente = None
        municipal = None
        registro = {"situacao": "CONSULTA_PREVIA"}
        try:
            # Releia após adquirir a trava: outro processo pode ter terminado
            # entre a primeira leitura e a aquisição, inclusive uma emissão.
            estado = json.loads(destino.read_text(encoding="utf-8"))
            if canal in estado["canais"] or any(
                entrada.get("situacao") != "REJEITADA" for entrada in estado["canais"].values()
            ):
                raise CommandError("Tentativa já registrada; consulte o resultado antes de novo envio.")
            if estado["parametros"] != parametros:
                raise CommandError("Parâmetros da DPS alterados durante a preparação; envio bloqueado.")
            xml = (pasta / "dps-assinada.xml").read_bytes()
            corpo = corpo_producao(xml, a1, SCHEMAS_EL) if canal == "municipal" else corpo_producao(xml, a1)
            estado["canais"][canal] = registro
            gravar()
            if canal == "municipal":
                municipal = ClienteMunicipalEL(os.environ.get("KSCENTRAL_EL_TOKEN", ""))
                status, retorno = municipal.consultar(identificador, ambiente=1)
                ausente = dps_ausente(status, retorno)
            else:
                cliente = httpx.Client(verify=a1.contexto_tls(), timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
                resposta = cliente.get(f"{URL}/dps/{identificador}")
                status = resposta.status_code
                retorno = self.retorno(resposta)
                ausente = status == 404
            registro.update(consulta_antes_http=status, consulta_antes=retorno)
            if not ausente:
                registro["situacao"] = "NAO_ENVIADA_CONSULTA_PREVIA"
                gravar()
                raise CommandError("Consulta não confirmou ausência; nenhuma DPS enviada por este canal.")
            registro["situacao"] = "ENVIO_INICIADO"
            gravar()
            if municipal:
                status, retorno = municipal._chamar("POST", "nfse", corpo)
            else:
                resposta = cliente.post(f"{URL}/nfse", json=corpo)
                status, retorno = resposta.status_code, self.retorno(resposta)
            situacao = interpretar_retorno(status, retorno, identificador, 1)
            # Só uma rejeição estruturada 400/422 habilita avaliar o outro canal.
            if situacao == "REJEITADA" and (status not in (400, 422) or retorno.get("tipoAmbiente") != 1):
                situacao = "INDETERMINADA_NAO_RETRANSMITIR"
            registro.update(http=status, retorno=retorno, situacao=situacao)
            gravar()
            if municipal and situacao == "EM_PROCESSAMENTO":
                status_consulta, consulta = municipal.consultar(identificador, ambiente=1)
                resultado = interpretar_retorno(status_consulta, consulta, identificador, 1, consulta=True)
                # Recebimento 201 impede emissão pelo outro canal mesmo que o ADN rejeite depois.
                registro.update(consulta_apos_http=status_consulta, consulta_apos=consulta, resultado_consulta=resultado)
                if resultado == "XML_NFSE_DISPONIVEL_VALIDACAO_PENDENTE":
                    registro["situacao"] = resultado
                gravar()
            self.stdout.write(json.dumps({"canal": canal, "http": status, "situacao": registro["situacao"],
                                          "erros": retorno.get("erros", []) if isinstance(retorno, dict) else [],
                                          "resultado_consulta": registro.get("resultado_consulta")}, ensure_ascii=False))
        except (httpx.HTTPError, ValidationError) as erro:
            registro.update(situacao="INDETERMINADA_NAO_RETRANSMITIR", erro=type(erro).__name__)
            gravar()
            raise CommandError("Comunicação inconclusiva; consulte a DPS antes de qualquer novo envio.") from None
        finally:
            if cliente:
                cliente.close()
            if municipal:
                municipal.close()
            trava.unlink(missing_ok=True)
        self.stdout.write(f"Evidências: {pasta}")

    @staticmethod
    def retorno(resposta):
        try:
            return resposta.json()
        except ValueError:
            return {"resposta": resposta.text[:2000]}
