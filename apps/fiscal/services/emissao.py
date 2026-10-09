"""Orquestração fiscal: validação, numeração, envio único e consulta do resultado."""
import base64
import gzip
import hashlib

import httpx
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.catalogo.models import ServicoMunicipal
from apps.core.models import Anexo

from ..models import ConfiguracaoFiscal, NotaFiscal, SequenciaNumeracao, TentativaTransmissao
from .configuracao import carregar_a1, checklist
from .documentos import descompactar_nfse, validar_nfse
from .el_nacional import SCHEMAS_EL, ClienteMunicipalEL, dps_ausente, interpretar_retorno
from .homologacao import NS
from .producao import URL, preparar_dps_producao, validar_assinatura_schema


def validar_emissao(nota, config):
    if nota.empresa_id != config.empresa_id:
        raise ValidationError("Configuração de outra empresa.")
    if nota.competencia > timezone.localdate():
        raise ValidationError("A competência não pode estar no futuro.")
    for campo in ("tomador", "item_catalogo", "perfil", "contrato"):
        vinculo = getattr(nota, campo, None)
        if vinculo is not None and vinculo.empresa_id != nota.empresa_id:
            raise ValidationError("Todos os vínculos devem pertencer à mesma empresa.")
    if not nota.item_catalogo.ativo or not nota.perfil.ativo:
        raise ValidationError("Selecione um item e um perfil ativos.")
    if any(nota.tomador_snapshot.get(campo) != getattr(nota.tomador, campo)
           for campo in ("cpf_cnpj", "razao_social")):
        raise ValidationError("O tomador mudou. Edite, confira e salve o rascunho antes de transmitir.")
    pendentes = [nome for nome, ok in checklist(config, nota.competencia) if not ok]
    if pendentes:
        raise ValidationError(pendentes)
    if nota.empresa.regime_tributario != "SIMPLES" or not nota.empresa.optante_simples:
        raise ValidationError("O adaptador atual transmite ME/EPP optante do Simples.")
    if any(getattr(nota, campo) for campo in ("valor_deducoes", "desconto_incondicionado", "desconto_condicionado",
            "outras_retencoes", "valor_ir", "valor_inss", "valor_pis", "valor_cofins", "valor_csll")) or nota.iss_retido:
        raise ValidationError("Este adaptador ainda não transmite retenções ou descontos; mantenha a nota como rascunho.")
    item = nota.item_catalogo
    if item.pendencias_fiscais:
        raise ValidationError(item.pendencias_fiscais)
    if item.codigo_tributacao_nacional.item_lc116 != item.item_lc116.item:
        raise ValidationError("O código nacional precisa corresponder ao item da LC 116 selecionado.")
    if nota.aliquota_iss is None or nota.aliquota_iss != config.aliquota_iss:
        raise ValidationError("O ISS da nota deve corresponder à configuração vigente.")
    atuais = {"item_lc116": str(item.item_lc116_id), "codigo_tributacao_nacional": str(item.codigo_tributacao_nacional_id),
              "nbs": str(item.nbs_id), "codigo_tributacao_municipal": item.codigo_tributacao_municipal}
    if any(nota.servico_snapshot.get(campo) != valor for campo, valor in atuais.items()):
        raise ValidationError("O serviço mudou após salvar o rascunho. Edite, confira e salve antes de transmitir.")
    if config.canal_padrao == "MUNICIPAL_EL":
        servico = ServicoMunicipal.objects.filter(municipio_ibge=nota.empresa.municipio_ibge,
                    item_lc116=item.item_lc116.item, codigo_integracao=item.codigo_tributacao_municipal,
                    codigo_confirmado=True).first()
        if not servico:
            raise ValidationError("Confirme o código municipal do serviço antes de transmitir.")


@transaction.atomic
def preparar_tentativa(nota, config):
    nota = NotaFiscal.objects.select_for_update().select_related("empresa", "tomador", "item_catalogo__nbs",
                "item_catalogo__codigo_tributacao_nacional", "item_catalogo__item_lc116").get(pk=nota.pk, empresa=config.empresa)
    if nota.status != NotaFiscal.Status.RASCUNHO or nota.tentativas.exists() or nota.id_dps:
        raise ValidationError("A nota já tem uma tentativa de emissão. Consulte o resultado.")
    validar_emissao(nota, config)
    a1 = carregar_a1(config)
    seq, _ = SequenciaNumeracao.objects.get_or_create(empresa=nota.empresa, ambiente=config.ambiente,
                                                    serie=config.serie_dps)
    seq = SequenciaNumeracao.objects.select_for_update().get(pk=seq.pk)
    SequenciaNumeracao.objects.filter(pk=seq.pk).update(ultimo_numero=F("ultimo_numero") + 1)
    seq.refresh_from_db()
    item = nota.item_catalogo
    ident, xml = preparar_dps_producao(a1, seq.ultimo_numero, municipio=nota.empresa.municipio_ibge,
        inscricao_municipal=nota.empresa.inscricao_municipal,
        tomador={"cpf" if nota.tomador.tipo == "F" else "cnpj": nota.tomador.cpf_cnpj, "nome": nota.tomador.razao_social},
        codigo_nacional=item.codigo_tributacao_nacional.codigo, nbs=item.nbs.codigo,
        codigo_municipal=item.codigo_tributacao_municipal, descricao=nota.discriminacao,
        valor=nota.valor_servicos, aliquota_iss=nota.aliquota_iss, total_tributos_simples=config.total_tributos_simples,
        serie=str(config.serie_dps), competencia=nota.competencia, ambiente=config.ambiente)
    validar_assinatura_schema(xml, a1, SCHEMAS_EL, ambiente=config.ambiente)
    anexo = Anexo.criar(nota, "dps-assinada.xml", xml, retencao_anos=5)
    tentativa = TentativaTransmissao.objects.create(empresa=nota.empresa, nota=nota, canal=config.canal_padrao,
                    ambiente=config.ambiente, id_dps=ident, dps_assinada=anexo,
                    hash_requisicao=hashlib.sha256(xml).hexdigest(), situacao="ENVIO_INICIADO")
    nota.id_dps, nota.ambiente, nota.canal = ident, config.ambiente, config.canal_padrao
    nota.status = NotaFiscal.Status.TRANSMITINDO
    nota.emissao_snapshot = {"iss": str(nota.aliquota_iss), "tributos_aproximados": str(config.total_tributos_simples),
                            "fonte": config.fonte_tributacao, "configuracao": str(config.pk)}
    nota.save()
    return tentativa, a1


def nacional_url(ambiente):
    return URL if ambiente == 1 else "https://sefin.producaorestrita.nfse.gov.br/SefinNacional"


def json_resposta(resposta):
    try:
        resultado = resposta.json()
        return resultado if isinstance(resultado, dict) else {"resposta_nao_objeto": True}
    except ValueError:
        return {"resposta_nao_json": True}


@transaction.atomic
def registrar_resultado(tentativa, status, retorno, *, consulta=False):
    if not isinstance(retorno, dict):
        retorno = {"resposta_nao_objeto": True}
    tentativa = TentativaTransmissao.objects.select_for_update().select_related("nota__empresa").get(pk=tentativa.pk)
    nota = NotaFiscal.objects.select_for_update().get(pk=tentativa.nota_id)
    situacao = interpretar_retorno(status, retorno, tentativa.id_dps, tentativa.ambiente, consulta=consulta)
    if consulta:
        tentativa.consultas = [*tentativa.consultas, {"http": status, "situacao": situacao,
                                                  "erros": retorno.get("erros", [])}][-100:]
    else:
        tentativa.http_status = status
        tentativa.resposta = {k: v for k, v in retorno.items() if "xml" not in k.lower()}
    if nota.status == NotaFiscal.Status.AUTORIZADA:
        tentativa.save()
        return nota
    if situacao == "XML_NFSE_DISPONIVEL_VALIDACAO_PENDENTE":
        xml = descompactar_nfse(retorno)
        doc = validar_nfse(xml, tentativa.id_dps, tentativa.ambiente, nota.empresa.cnpj,
                           retorno["chaveAcesso"], tentativa.dps_assinada.ler())
        nota.xml_autorizado = Anexo.criar(nota, "nfse.xml", xml, retencao_anos=5)
        nota.numero_nfse = doc.findtext(f".//{{{NS}}}nNFSe")
        nota.chave_acesso = retorno["chaveAcesso"]
        nota.autorizada_em = timezone.now()
        nota.status = NotaFiscal.Status.AUTORIZADA
        tentativa.situacao = "AUTORIZADA"
        nota.save()
        if tentativa.ambiente == 1:
            from apps.financeiro.services.recebiveis import gerar_recebivel
            try:
                gerar_recebivel(nota)
            except ValidationError as erro:
                # O aceite fiscal não depende do cadastro financeiro. Preserve
                # a autorização e permita gerar o recebível depois de corrigir.
                nota.emissao_snapshot["recebivel_pendente"] = erro.messages
                nota.save()
    else:
        tentativa.situacao = situacao
        if situacao == "REJEITADA" and status in (400, 422) and retorno.get("tipoAmbiente") == tentativa.ambiente:
            nota.status = NotaFiscal.Status.REJEITADA
        elif situacao == "EM_PROCESSAMENTO":
            nota.status = NotaFiscal.Status.EM_PROCESSAMENTO
        else:
            nota.status = NotaFiscal.Status.ERRO_COMUNICACAO
        nota.save()
    tentativa.save()
    return nota


def transmitir(nota):
    config = ConfiguracaoFiscal.objects.select_related("empresa", "certificado", "token_municipal").get(empresa=nota.empresa)
    tentativa, a1 = preparar_tentativa(nota, config)
    xml = tentativa.dps_assinada.ler()
    corpo = {"dpsXmlGZipB64": base64.b64encode(gzip.compress(xml)).decode("ascii")}
    try:
        if tentativa.canal == "MUNICIPAL_EL":
            cliente = ClienteMunicipalEL(config.token_municipal.ler())
            try:
                status, retorno = cliente.consultar(tentativa.id_dps, tentativa.ambiente)
                if not dps_ausente(status, retorno):
                    return registrar_resultado(tentativa, status, retorno, consulta=True)
                caminho = "nfse" if tentativa.ambiente == 1 else "homologacao/nfse"
                status, retorno = cliente._chamar("POST", caminho, corpo)
            finally:
                cliente.close()
        else:
            with httpx.Client(verify=a1.contexto_tls(), timeout=60, follow_redirects=False) as cliente:
                existente = cliente.get(f"{nacional_url(tentativa.ambiente)}/dps/{tentativa.id_dps}")
                if existente.status_code != 404:
                    raise ValidationError("Consulta prévia nacional não confirmou ausência; consulte a DPS.")
                resposta = cliente.post(f"{nacional_url(tentativa.ambiente)}/nfse", json=corpo)
                status, retorno = resposta.status_code, json_resposta(resposta)
        return registrar_resultado(tentativa, status, retorno)
    except (httpx.HTTPError, ValidationError):
        with transaction.atomic():
            bloqueada = NotaFiscal.objects.select_for_update().get(pk=nota.pk)
            if bloqueada.status != NotaFiscal.Status.AUTORIZADA:
                bloqueada.status = NotaFiscal.Status.ERRO_COMUNICACAO
                bloqueada.save()
        raise ValidationError("Resultado inconclusivo. Consulte esta DPS; não repita a emissão.") from None


def consultar(nota):
    tentativa = nota.tentativas.first()
    if not tentativa:
        raise ValidationError("A nota não tem transmissão para consultar.")
    config = ConfiguracaoFiscal.objects.select_related("empresa", "certificado", "token_municipal").get(empresa=nota.empresa)
    if tentativa.canal == "MUNICIPAL_EL":
        cliente = ClienteMunicipalEL(config.token_municipal.ler())
        try:
            status, retorno = cliente.consultar(tentativa.id_dps, tentativa.ambiente)
        finally:
            cliente.close()
    else:
        a1 = carregar_a1(config)
        with httpx.Client(verify=a1.contexto_tls(), timeout=45, follow_redirects=False) as cliente:
            resposta = cliente.get(f"{nacional_url(tentativa.ambiente)}/dps/{tentativa.id_dps}")
            retorno = json_resposta(resposta)
            if resposta.status_code == 200 and retorno.get("chaveAcesso"):
                resposta = cliente.get(f"{nacional_url(tentativa.ambiente)}/nfse/{retorno['chaveAcesso']}")
                retorno = json_resposta(resposta)
                retorno.setdefault("idDPS", tentativa.id_dps)
            status = resposta.status_code
    return registrar_resultado(tentativa, status, retorno, consulta=True)
