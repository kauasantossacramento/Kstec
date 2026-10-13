"""Pacote fiscal revisável e envio explícito com histórico e proteção contra repetição."""
import hashlib
import io
import json
import re
import smtplib
import zipfile

from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.certidoes.models import Certidao, TipoCertidao
from apps.core.models import Anexo
from apps.core.pdf import renderizar_pdf
from apps.financeiro.models import PlanilhaCustos
from apps.operacao.models import RelatorioAtividades

from ..models import EntregaNota, NotaFiscal
from .pdf_nfse import garantir_pdf


def emails(texto):
    destinos = list(dict.fromkeys(p.strip() for p in re.split(r"[;,\s]+", texto) if p.strip()))
    if not destinos or len(destinos) > 20:
        raise ValidationError("Informe de 1 a 20 destinatários válidos.")
    for destino in destinos:
        validate_email(destino)
    return destinos


def certidoes_validas(contrato):
    hoje = timezone.localdate()
    exigidas = list(contrato.certidoes_exigidas.all())
    if any(t.empresa_id != contrato.empresa_id or not t.ativo for t in exigidas):
        raise ValidationError("Revise os tipos de certidão exigidos pelo contrato.")
    tipos = exigidas or list(TipoCertidao.objects.filter(empresa=contrato.empresa, ativo=True))
    selecionadas, faltas = [], []
    for tipo in tipos:
        certs = Certidao.objects.filter(empresa=contrato.empresa, tipo=tipo, ativo=True,
              data_emissao__lte=hoje, data_validade__gte=hoje,
              situacao__in=["NEGATIVA", "POSITIVA_COM_EFEITO_NEGATIVA"]).exclude(arquivo="").order_by("-data_validade")
        cert = certs.first()
        if cert:
            selecionadas.append(cert)
        elif exigidas:
            faltas.append(tipo.nome)
    if faltas:
        raise ValidationError("Certidões exigidas ausentes, sem PDF ou sem validade: " + ", ".join(faltas))
    if not selecionadas:
        raise ValidationError("Cadastre certidões válidas com PDF para montar o kit contratual.")
    return selecionadas


def documentos_contrato(nota):
    """Documentos da competência. Cada exigência é atendida pelo documento aprovado no sistema OU por um documento
    enviado (ex.: PDF assinado) do mesmo tipo e competência em Contrato → Documentos."""
    from apps.contratos.models import DocumentoContrato
    from apps.sla.services.relatorio import aprovado as sla_aprovado

    contrato = nota.contrato
    if contrato.empresa_id != nota.empresa_id or contrato.cliente_id != nota.tomador_id:
        raise ValidationError("Contrato e tomador precisam pertencer à mesma empresa e cliente.")
    competencia = nota.competencia.replace(day=1)
    relatorio = RelatorioAtividades.objects.filter(empresa=nota.empresa, contrato=contrato,
                       competencia=competencia, status="APROVADO", ativo=True).order_by("-versao").first()
    planilha = PlanilhaCustos.objects.filter(empresa=nota.empresa, contrato=contrato,
                       competencia=competencia, status="APROVADO", ativo=True).order_by("-versao").first()
    enviados = {}
    for doc in DocumentoContrato.objects.filter(contrato=contrato, competencia=competencia, ativo=True).select_related("anexo"):
        enviados.setdefault(doc.tipo, doc)
    sla = sla_aprovado(contrato, competencia) if contrato.exige_relatorio_sla else None
    faltas = []
    if not (relatorio and relatorio.pdf_id) and "RELATORIO_ATIVIDADES" not in enviados:
        faltas.append("Relatório de atividades aprovado (ou PDF assinado enviado) na mesma competência")
    if not (planilha and planilha.xlsx_id and planilha.pdf_id) and "PLANILHA_CUSTOS" not in enviados:
        faltas.append("Planilha de custos aprovada (ou PDF assinado enviado) na mesma competência")
    if contrato.exige_relatorio_sla and not (sla and sla.pdf_id) and "RELATORIO_SLA" not in enviados:
        faltas.append("Relatório de SLA aprovado (ou PDF enviado) na mesma competência")
    if faltas:
        raise ValidationError(faltas)
    return {"relatorio": relatorio if relatorio and relatorio.pdf_id else None,
            "planilha": planilha if planilha and planilha.xlsx_id and planilha.pdf_id else None,
            "sla": sla if sla and sla.pdf_id else None, "enviados": list(enviados.values()),
            "certidoes": certidoes_validas(contrato)}


def arquivos_documentos(docs, descricoes=None):
    """PDFs dos documentos da competência. `descricoes` (dict) recebe nome do arquivo → descrição para o índice."""
    descricoes = {} if descricoes is None else descricoes
    arquivos = []

    def incluir(anexo, descricao):
        arquivos.append((anexo.nome, anexo.ler()))
        descricoes[anexo.nome] = descricao
    assinado = " — assinado digitalmente (ICP-Brasil)"
    if docs["relatorio"]:
        incluir(docs["relatorio"].pdf, f"Relatório de atividades{assinado}")
    if docs["planilha"]:
        # Ao cliente vai só o PDF assinado; o XLSX é de uso interno.
        incluir(docs["planilha"].pdf, f"Demonstrativo de custos{assinado}")
    if docs["sla"]:
        incluir(docs["sla"].pdf, f"Relatório de SLA{assinado}")
    for doc in docs["enviados"]:
        if doc.tipo == "CONTRATO":
            continue  # o contrato o cliente já possui; fica só no arquivo do sistema
        if (doc.tipo == "RELATORIO_ATIVIDADES" and docs["relatorio"]) or (doc.tipo == "PLANILHA_CUSTOS" and docs["planilha"])                 or (doc.tipo == "RELATORIO_SLA" and docs["sla"]):
            continue  # o documento aprovado no sistema prevalece
        incluir(doc.anexo, doc.titulo + (" — assinado" if doc.assinado else ""))
    return arquivos


def ids_documentos(docs):
    return {"relatorio": str(docs["relatorio"].pk) if docs["relatorio"] else None,
            "planilha": str(docs["planilha"].pk) if docs["planilha"] else None,
            "sla": str(docs["sla"].pk) if docs["sla"] else None,
            "enviados": sorted(str(d.pk) for d in docs["enviados"])}


def zip_bytes(arquivos):
    if sum(len(c) for _, c in arquivos) > 15_000_000:
        raise ValidationError("Pacote acima de 15 MB. Reduza os PDFs antes de preparar o e-mail.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos:
            z.writestr(nome, conteudo)
    return buf.getvalue()


@transaction.atomic
def preparar_entrega(nota, destinatarios, assunto, mensagem):
    nota = NotaFiscal.objects.select_for_update(of=("self",)).select_related("contrato", "tomador").get(pk=nota.pk)
    if nota.status != "AUTORIZADA" or nota.ambiente != 1:
        raise ValidationError("Envie apenas NFS-e autorizada em produção.")
    destinos = emails(destinatarios)
    if not assunto.strip() or len(assunto) > 200 or any(c in assunto for c in "\r\n"):
        raise ValidationError("Informe um assunto válido, sem quebras de linha.")
    if len(mensagem) > 10000:
        raise ValidationError("Mensagem acima de 10.000 caracteres.")
    # Cheque os requisitos antes de renderizar ou arquivar um pacote.
    documentos = documentos_contrato(nota) if nota.contrato_id else None
    pdf = garantir_pdf(nota)
    arquivos = [(pdf.nome, pdf.ler()), (f"nfse_{nota.numero_nfse}.xml", nota.xml_autorizado.ler())]
    manifesto = {"nota": str(nota.pk), "contrato": str(nota.contrato_id) if nota.contrato_id else None,
                 "competencia": str(nota.competencia.replace(day=1)), "certidoes": []}
    descricoes = {pdf.nome: f"Nota Fiscal de Serviço eletrônica nº {nota.numero_nfse} (DANFSe)"}
    if documentos:
        certs = documentos["certidoes"]
        arquivos.extend(arquivos_documentos(documentos, descricoes))
        cert_arquivos = []
        for indice, cert in enumerate(certs, 1):
            with cert.arquivo.open("rb") as f:
                dados = f.read(15_000_001)
            if not dados.startswith(b"%PDF-"):
                raise ValidationError(f"O arquivo da certidão {cert.tipo.nome} não é PDF.")
            nome = f"{indice:02d}_{slugify(cert.tipo.nome)[:80]}.pdf"
            cert_arquivos.append((nome, dados))
            descricoes[f"certidoes_{nome}"] = (f"{cert.tipo.nome} — {cert.get_situacao_display().lower()}, "
                                               f"válida até {cert.data_validade:%d/%m/%Y}")
            manifesto["certidoes"].append({"id": str(cert.pk), "tipo": str(cert.tipo_id), "nome": cert.tipo.nome,
                                          "validade": str(cert.data_validade), "sha256": hashlib.sha256(dados).hexdigest()})
        indice_cert = renderizar_pdf("pdf/certidoes_entrega.html", {"nota": nota, "certidoes": certs, "empresa": nota.empresa})
        arquivos.append(("kit_certidoes.zip", zip_bytes([("00_indice.pdf", indice_cert), *cert_arquivos])))
        descricoes["certidoes_00_indice.pdf"] = "Relação das certidões de regularidade vigentes"
        manifesto.update(ids_documentos(documentos))
    manifesto["arquivos"] = [{"nome": n, "tamanho": len(c), "sha256": hashlib.sha256(c).hexdigest()} for n, c in arquivos]
    if documentos:
        # O índice lista exatamente os PDFs que seguem anexos ao e-mail (ver anexos_email).
        itens = [{"arquivo": n, "descricao": descricoes.get(n, n)}
                 for n, _, _ in anexos_email(zip_bytes(arquivos))]
        arquivos.insert(0, ("00_indice.pdf", renderizar_pdf("pdf/pacote_entrega.html", {"nota": nota,
                                     "itens": itens, "empresa": nota.empresa})))
    arquivos.append(("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8")))
    pacote = Anexo.criar(nota, f"pacote_nfse_{nota.numero_nfse}.zip", zip_bytes(arquivos), retencao_anos=5)
    return EntregaNota.objects.create(empresa=nota.empresa, nota=nota, destinatarios=destinos,
                                      assunto=assunto.strip(), mensagem=mensagem, pacote=pacote, manifesto=manifesto)


def revalidar_entrega(entrega):
    nota = entrega.nota
    if nota.status != "AUTORIZADA" or nota.ambiente != 1:
        raise ValidationError("A nota não está autorizada em produção.")
    if entrega.manifesto.get("contrato") != (str(nota.contrato_id) if nota.contrato_id else None):
        raise ValidationError("O vínculo contratual mudou após preparar o pacote.")
    if nota.contrato_id:
        atuais = ids_documentos(documentos_contrato(nota))
        if any(atuais[k] != entrega.manifesto.get(k) for k in atuais):
            raise ValidationError("Há nova versão aprovada dos documentos. Prepare um novo pacote.")
        exigidas = {str(pk) for pk in nota.contrato.certidoes_exigidas.values_list("pk", flat=True)}
        incluidas = {item["tipo"] for item in entrega.manifesto["certidoes"]}
        if not exigidas.issubset(incluidas):
            raise ValidationError("O contrato passou a exigir outra certidão. Prepare um novo pacote.")
        for item in entrega.manifesto["certidoes"]:
            cert = Certidao.objects.filter(pk=item["id"], empresa=entrega.empresa, ativo=True, tipo__ativo=True,
                   data_emissao__lte=timezone.localdate(), data_validade__gte=timezone.localdate(),
                   situacao__in=["NEGATIVA", "POSITIVA_COM_EFEITO_NEGATIVA"]).first()
            if cert is None or str(cert.data_validade) != item["validade"]:
                raise ValidationError("Uma certidão do pacote perdeu a validade. Prepare um novo pacote.")
            with cert.arquivo.open("rb") as arquivo:
                if hashlib.sha256(arquivo.read(15_000_001)).hexdigest() != item["sha256"]:
                    raise ValidationError("Uma certidão foi alterada após montar o pacote.")


def anexos_email(dados):
    """PDFs do pacote, um a um (o kit de certidões é aberto), para anexar ao e-mail sem zip.
    XML, XLSX e manifesto ficam no pacote arquivado (baixável na tela da nota)."""
    saida = []
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        for info in z.infolist():
            nome = info.filename
            if nome.endswith(".zip"):
                prefixo = nome[:-4].replace("kit_", "")
                with zipfile.ZipFile(io.BytesIO(z.read(nome))) as interno:
                    saida += [(f"{prefixo}_{i.filename}", interno.read(i.filename)) for i in interno.infolist()]
                continue
            saida.append(("00_indice_do_pacote.pdf" if nome == "00_indice.pdf" else nome, z.read(nome)))
    return [(n, c, "application/pdf") for n, c in saida if n.lower().endswith(".pdf")]


def enviar_entrega(entrega):
    with transaction.atomic():
        atual = EntregaNota.objects.select_for_update(of=("self",)).select_related("nota__contrato", "pacote").get(pk=entrega.pk)
        if atual.status != "PREPARADA":
            raise ValidationError("Este envio já foi iniciado. Confira o histórico antes de preparar outro.")
        revalidar_entrega(atual)
        dados = atual.pacote.ler()
        if hashlib.sha256(dados).hexdigest() != atual.pacote.hash_sha256:
            raise ValidationError("O pacote arquivado foi alterado.")
        atual.status = "ENVIANDO"
        atual.save()
    from apps.core.services.email import conexao

    conexao_smtp, remetente, copia = conexao("DOCUMENTOS", atual.empresa)
    mail = EmailMessage(atual.assunto, atual.mensagem, remetente, atual.destinatarios, bcc=copia, connection=conexao_smtp)
    for nome, conteudo, tipo in anexos_email(dados):
        mail.attach(nome, conteudo, tipo)
    try:
        enviados = mail.send(fail_silently=False)
        if enviados != 1:
            raise OSError("Backend não confirmou envio.")
    except (smtplib.SMTPException, OSError):
        atual.status = "INCERTA"
        atual.save()
        raise ValidationError("Envio sem confirmação. Confira o servidor de e-mail antes de preparar outro envio.") from None
    simulacao = type(conexao_smtp).__module__.rsplit(".", 1)[-1] in ("console", "filebased", "locmem", "dummy")
    atual.status = "SIMULADA" if simulacao else "ENVIADA"
    atual.enviado_em = timezone.now()
    atual.save()
    return atual
