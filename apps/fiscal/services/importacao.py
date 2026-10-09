"""Incorporação de NFS-e confirmada por consulta autenticada, sem retransmitir."""
import hashlib
from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from lxml import etree

from apps.cadastros.models import Pessoa
from apps.catalogo.models import ItemCatalogo
from apps.core.models import Anexo
from apps.financeiro.services.recebiveis import gerar_recebivel

from ..models import ConfiguracaoFiscal, NotaFiscal, SequenciaNumeracao, TentativaTransmissao
from .documentos import conteudo, descompactar_nfse, validar_nfse
from .homologacao import NS
from .rascunhos import salvar


@transaction.atomic
def importar_confirmada(empresa, xml_local, retorno_autenticado, canal):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    doc_local = etree.fromstring(xml_local, parser)
    xml = descompactar_nfse(retorno_autenticado)
    doc = etree.fromstring(xml, parser)
    if conteudo(doc) != conteudo(doc_local):
        raise ValidationError("O XML local difere do documento recuperado pela consulta autenticada.")
    dps = doc.find(f".//{{{NS}}}DPS/{{{NS}}}infDPS")
    ambiente = int(dps.findtext(f"{{{NS}}}tpAmb"))
    chave = retorno_autenticado["chaveAcesso"]
    validar_nfse(xml, dps.get("Id"), ambiente, empresa.cnpj, chave)
    if retorno_autenticado.get("tipoAmbiente") != ambiente or canal not in ConfiguracaoFiscal.Canal.values:
        raise ValidationError("Ambiente ou canal divergente.")
    existente = NotaFiscal.objects.filter(empresa=empresa, ambiente=ambiente, chave_acesso=chave).first()
    if existente:
        registrar_origem(existente, doc, canal)
        return existente, False
    valor = Decimal(dps.findtext(f"{{{NS}}}valores/{{{NS}}}vServPrest/{{{NS}}}vServ"))
    tipo_ret = dps.findtext(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}tribMun/{{{NS}}}tpRetISSQN")
    trib_fed = dps.find(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}tribFed")
    if (tipo_ret != "1" or trib_fed is not None
            or dps.find(f"{{{NS}}}valores/{{{NS}}}vDescCondIncond") is not None
            or dps.find(f"{{{NS}}}valores/{{{NS}}}vDedRed") is not None):
        raise ValidationError("A importação atual suporta notas sem retenções, descontos e deduções.")
    cserv = dps.find(f"{{{NS}}}serv/{{{NS}}}cServ")
    item = ItemCatalogo.objects.filter(empresa=empresa,
        codigo_tributacao_nacional__codigo=cserv.findtext(f"{{{NS}}}cTribNac"),
        nbs__codigo=cserv.findtext(f"{{{NS}}}cNBS"),
        codigo_tributacao_municipal=cserv.findtext(f"{{{NS}}}cIntContrib") or "").first()
    if not item:
        raise ValidationError("Cadastre o serviço com os códigos do XML antes de importar.")
    toma = dps.find(f"{{{NS}}}toma")
    documento = toma.findtext(f"{{{NS}}}CPF") or toma.findtext(f"{{{NS}}}CNPJ")
    pessoa, _ = Pessoa.objects.get_or_create(empresa=empresa, cpf_cnpj=documento,
        defaults={"tipo": "F" if len(documento) == 11 else "J", "razao_social": toma.findtext(f"{{{NS}}}xNome")})
    config = ConfiguracaoFiscal.objects.get(empresa=empresa)
    if not config.perfil_padrao:
        raise ValidationError("Defina um perfil padrão para importar.")
    if config.perfil_padrao.iss_retido or any(getattr(config.perfil_padrao, "reter_" + t) for t in ("ir", "inss", "pis", "cofins", "csll")):
        raise ValidationError("O perfil padrão precisa corresponder à nota importada sem retenções.")
    nota = NotaFiscal(empresa=empresa, tomador=pessoa, item_catalogo=item, perfil=config.perfil_padrao,
        competencia=date.fromisoformat(dps.findtext(f"{{{NS}}}dCompet")),
        discriminacao=cserv.findtext(f"{{{NS}}}xDescServ"), valor_servicos=valor,
        aliquota_iss=Decimal(dps.findtext(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}tribMun/{{{NS}}}pAliq")))
    salvar(nota)
    nota.numero_nfse = doc.findtext(f".//{{{NS}}}nNFSe")
    nota.chave_acesso, nota.id_dps, nota.ambiente, nota.canal = chave, dps.get("Id"), ambiente, canal
    nota.autorizada_em = datetime.fromisoformat(doc.findtext(f".//{{{NS}}}dhProc"))
    nota.status = "AUTORIZADA"
    nota.xml_autorizado = Anexo.criar(nota, "nfse.xml", xml, retencao_anos=5)
    nota.emissao_snapshot = {"origem": "Importada e confirmada por consulta nacional autenticada",
                            "tributos_aproximados": dps.findtext(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}totTrib/{{{NS}}}pTotTribSN")}
    nota.save()
    registrar_origem(nota, doc, canal)
    seq, _ = SequenciaNumeracao.objects.get_or_create(empresa=empresa, ambiente=ambiente,
                                            serie=int(dps.findtext(f"{{{NS}}}serie")))
    seq.ultimo_numero = max(seq.ultimo_numero, int(dps.findtext(f"{{{NS}}}nDPS")))
    seq.save()
    if ambiente == 1:
        try:
            gerar_recebivel(nota)
        except ValidationError as erro:
            nota.emissao_snapshot["recebivel_pendente"] = erro.messages
            nota.save()
    return nota, True


def registrar_origem(nota, doc, canal):
    if nota.tentativas.exists():
        return
    dps = etree.tostring(doc.find(f".//{{{NS}}}DPS"), encoding="UTF-8", xml_declaration=True)
    anexo = Anexo.criar(nota, "dps-incorporada.xml", dps,
                        descricao="DPS incorporada ao XML autorizado; registro de importação, sem novo POST.", retencao_anos=5)
    TentativaTransmissao.objects.create(empresa=nota.empresa, nota=nota, canal=canal, ambiente=nota.ambiente,
        id_dps=nota.id_dps, situacao="IMPORTADA_AUTORIZADA", http_status=200, dps_assinada=anexo,
        hash_requisicao=hashlib.sha256(dps).hexdigest(), resposta={"origem": "Importação confirmada pela API nacional, sem transmissão"})
