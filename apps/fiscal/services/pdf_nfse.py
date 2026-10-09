"""DANFSe local a partir exclusivamente do XML autorizado (NT 008 v1.02)."""
import base64
import hashlib
import io
from datetime import date, datetime
from decimal import Decimal

import qrcode
from django.core.exceptions import ValidationError
from django.db import transaction
from lxml import etree
from pypdf import PdfReader

from apps.core.models import Anexo
from apps.core.pdf import caminho_static, renderizar_pdf
from apps.core.validadores import formatar_doc

from ..models import NotaFiscal
from .homologacao import NS


def texto(no, caminho, padrao="-"):
    if no is None:
        return padrao
    return no.findtext("/".join(f"{{{NS}}}{t}" for t in caminho.split("/"))) or padrao


def pessoa_xml(no, fallback=None):
    fonte = no if no is not None else fallback
    end = fonte.find(f"{{{NS}}}end") if fonte is not None else None
    if end is None and fallback is not None:
        end = fallback.find(f"{{{NS}}}enderNac")
    municipio = texto(end, "endNac/cMun", texto(end, "cMun"))
    cep = texto(end, "endNac/CEP", texto(end, "CEP"))
    return {"nome": texto(fonte, "xNome", texto(fallback, "xNome")),
            "doc": formatar_doc(texto(fonte, "CNPJ", texto(fonte, "CPF", texto(fonte, "NIF")))),
            "im": texto(fonte, "IM"), "fone": texto(fonte, "fone"), "email": texto(fonte, "email"),
            "municipio": municipio, "municipio_ibge": municipio, "cep": cep,
            "endereco": ", ".join(texto(end, tag) for tag in ("xLgr", "nro", "xCpl", "xBairro") if texto(end, tag) != "-") or "-"}


def dados_xml(nota):
    if nota.status != "AUTORIZADA" or not nota.xml_autorizado_id:
        raise ValidationError("O PDF exige uma NFS-e autorizada com XML arquivado.")
    xml = nota.xml_autorizado.ler()
    if hashlib.sha256(xml).hexdigest() != nota.xml_autorizado.hash_sha256:
        raise ValidationError("O XML arquivado foi alterado após a autorização.")
    doc = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    inf = doc.find(f"{{{NS}}}infNFSe")
    if inf is None or inf.get("Id") != "NFS" + nota.chave_acesso or texto(inf, "cStat") != "100":
        raise ValidationError("Identidade ou situação do XML divergente da nota autorizada.")
    dps = inf.find(f"{{{NS}}}DPS/{{{NS}}}infDPS")
    if dps is None or dps.get("Id") != nota.id_dps or texto(dps, "tpAmb") != str(nota.ambiente):
        raise ValidationError("DPS ou ambiente divergente do XML autorizado.")
    if inf.find(f"{{{NS}}}IBSCBS") is not None or dps.find(f"{{{NS}}}IBSCBS") is not None:
        raise ValidationError("Este gerador de DANFSe atende o fluxo do Simples sem grupo IBS/CBS. Amplie o leiaute antes de imprimir este XML.")
    prest = pessoa_xml(dps.find(f"{{{NS}}}prest"), inf.find(f"{{{NS}}}emit"))
    if prest["nome"] == "-":
        prest["nome"] = texto(inf, "emit/xNome")
    if prest["municipio"] == texto(inf, "emit/enderNac/cMun"):
        prest["municipio"] = texto(inf, "xLocEmi") + " / " + texto(inf, "emit/enderNac/UF")
    valores = inf.find(f"{{{NS}}}valores")
    mun = dps.find(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}tribMun")
    fed = dps.find(f"{{{NS}}}valores/{{{NS}}}trib/{{{NS}}}tribFed")
    qr = io.BytesIO()
    qrcode.make("https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave=" + nota.chave_acesso).save(qr, format="PNG")
    def dinheiro(caminho):
        valor = texto(dps, caminho)
        return Decimal(valor) if valor != "-" else None
    retencoes = {nome: texto(fed, campo) for nome, campo in
                 (("IRRF", "vRetIRRF"), ("INSS", "vRetCP"), ("CSLL", "vRetCSLL"), ("PIS", "piscofins/vPis"), ("COFINS", "piscofins/vCofins"))}
    return {"nota": nota, "logo_nfse": caminho_static("img/nfse-nacional.png"),
        "qr": "data:image/png;base64," + base64.b64encode(qr.getvalue()).decode(),
        "municipio": texto(inf, "xLocEmi"), "uf": texto(inf, "emit/enderNac/UF"),
        "ambger": {"1": "Municipal", "2": "Nacional"}.get(texto(inf, "ambGer"), texto(inf, "ambGer")),
        "numero": texto(inf, "nNFSe"), "competencia": date.fromisoformat(texto(dps, "dCompet")),
        "emitida_em": datetime.fromisoformat(texto(inf, "dhProc")), "dps_em": datetime.fromisoformat(texto(dps, "dhEmi")),
        "numero_dps": texto(dps, "nDPS"), "serie": texto(dps, "serie"),
        "emitente": {"1": "Prestador", "2": "Tomador", "3": "Intermediário"}.get(texto(dps, "tpEmit"), "-"),
        "finalidade": texto(dps, "IBSCBS/finNFSe"), "prest": prest,
        "sn": {"1": "Não optante", "2": "Optante - MEI", "3": "Optante - ME/EPP"}.get(texto(dps, "prest/regTrib/opSimpNac"), "-"),
        "regime_sn": texto(dps, "prest/regTrib/regApTribSN"), "regime_especial": texto(dps, "prest/regTrib/regEspTrib"),
        "toma": pessoa_xml(dps.find(f"{{{NS}}}toma")), "intermediario": pessoa_xml(dps.find(f"{{{NS}}}interm")),
        "nacional": texto(dps, "serv/cServ/cTribNac"), "municipal": texto(dps, "serv/cServ/cIntContrib"),
        "nbs": texto(dps, "serv/cServ/cNBS"), "descricao_tributacao": texto(inf, "xTribNac"),
        "local": texto(inf, "xLocPrestacao"), "descricao": texto(dps, "serv/cServ/xDescServ"),
        "trib_iss": {"1": "Operação tributável", "2": "Imunidade", "3": "Exportação", "4": "Não incidência"}.get(texto(mun, "tribISSQN"), "-"),
        "incidencia": texto(inf, "xLocIncid"), "imunidade": texto(mun, "tpImunidade"),
        "suspensao": texto(mun, "exigSusp/tpSusp"), "processo": texto(mun, "exigSusp/nProcesso"),
        "beneficio": texto(mun, "BM/nBM"), "iss_retido": {"1": "Não retido", "2": "Retido pelo tomador", "3": "Retido pelo intermediário"}.get(texto(mun, "tpRetISSQN"), "-"),
        "valor": dinheiro("valores/vServPrest/vServ"), "desc_inc": dinheiro("valores/vDescCondIncond/vDescIncond"),
        "desc_cond": dinheiro("valores/vDescCondIncond/vDescCond"), "deducoes": texto(valores, "vCalcDR"),
        "base": texto(valores, "vBC"), "iss": texto(valores, "vISSQN"),
        "aliquota": texto(valores, "pAliqAplic", texto(mun, "pAliq")), "liquido": Decimal(texto(valores, "vLiq")),
        "retencoes": retencoes, "ibs": texto(inf, "IBSCBS/valores/vIBS"), "cbs": texto(inf, "IBSCBS/valores/vCBS"),
        "trib_aprox": texto(dps, "valores/trib/totTrib/pTotTribSN"),
        "info": texto(dps, "serv/cServ/xInfComp"), "hash_xml": nota.xml_autorizado.hash_sha256}


@transaction.atomic
def garantir_pdf(nota):
    nota = NotaFiscal.objects.select_for_update().select_related("xml_autorizado", "pdf", "empresa").get(pk=nota.pk)
    dados = dados_xml(nota)
    if nota.pdf_id:
        return nota.pdf
    pdf = renderizar_pdf("pdf/nfse.html", dados)
    if len(PdfReader(io.BytesIO(pdf)).pages) != 1:
        raise ValidationError("O DANFSe deve caber em uma página. Revise o tamanho dos campos antes de disponibilizar.")
    nota.pdf = Anexo.criar(nota, f"nfse_{nota.numero_nfse}.pdf", pdf, descricao="DANFSe v2.0 gerado do XML autorizado · NT 008 v1.02", retencao_anos=5)
    nota.save()
    return nota.pdf
