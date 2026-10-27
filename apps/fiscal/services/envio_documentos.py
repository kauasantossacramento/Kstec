"""Envio dos documentos da NFS-e ao órgão, confirmado pelo WhatsApp.

Depois da autorização (ou quando os documentos ficam prontos), monta o e-mail da agenda de faturamento
(destinatários, assunto e texto) e manda ao administrador, no WhatsApp, o corpo do e-mail e os PDFs que seguirão
anexos — documentos ainda em rascunho vão como PRÉVIA. "SIM código" aprova e assina os rascunhos exatamente como
mostrados, gera o pacote e envia o e-mail; "NAO código" cancela. Nada sai sem a resposta.
"""

import hashlib
import logging
import re
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import Anexo
from apps.core.pdf import renderizar_pdf
from apps.core.templatetags.ks import brl

from ..models import NotaFiscal

ACAO = "fiscal.envio_documentos"
PRAZO_HORAS = 72
JANELA_DIAS = 40
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Documentos da competência
# ---------------------------------------------------------------------------

def _ultimo(modelo, nota, **filtros):
    return modelo.objects.filter(empresa=nota.empresa, contrato=nota.contrato, competencia=nota.competencia.replace(day=1),
                                 ativo=True, **filtros).order_by("-versao").first()


def garantir_rascunhos(ciclo):
    """Cria os rascunhos que faltarem: relatório de atividades e planilha (ciclos.preparar_documentos) e SLA."""
    from apps.faturamento.services.ciclos import preparar_documentos
    from apps.sla.models import RelatorioSLA
    from apps.sla.services import relatorio as sla

    preparar_documentos(ciclo)
    nota = ciclo.nota
    contrato = nota.contrato
    if contrato.exige_relatorio_sla and contrato.sistemas.filter(ativo=True).exists() \
            and not RelatorioSLA.objects.filter(contrato=contrato, competencia=nota.competencia.replace(day=1)).exists():
        try:
            sla.novo(contrato, nota.competencia)
        except ValidationError as erro:
            log.warning("SLA não criado para %s: %s", contrato, erro)


def levantar(nota):
    """Situação de cada documento exigido: aprovado (vai assinado), rascunho (vai como prévia e é aprovado no SIM)
    ou falta (impede o envio). Retorna dict com 'docs', 'rascunhos', 'faltas', 'enviados', 'certidoes'."""
    from apps.contratos.models import DocumentoContrato
    from apps.financeiro.models import PlanilhaCustos
    from apps.operacao.models import RelatorioAtividades
    from apps.sla.models import RelatorioSLA

    from .entregas import certidoes_validas

    contrato = nota.contrato
    enviados = {}
    for doc in DocumentoContrato.objects.filter(contrato=contrato, competencia=nota.competencia.replace(day=1),
                                                ativo=True).select_related("anexo"):
        enviados.setdefault(doc.tipo, doc)
    exigidos = [("relatorio", RelatorioAtividades, "RELATORIO_ATIVIDADES", "relatório de atividades"),
                ("planilha", PlanilhaCustos, "PLANILHA_CUSTOS", "planilha de custos")]
    if contrato.exige_relatorio_sla:
        exigidos.append(("sla", RelatorioSLA, "RELATORIO_SLA", "relatório de SLA"))
    docs, rascunhos, faltas = {}, {}, []
    for chave, modelo, tipo, nome in exigidos:
        aprovado = _ultimo(modelo, nota, status="APROVADO")
        if aprovado and aprovado.pdf_id:
            docs[chave] = aprovado
            continue
        if tipo in enviados:
            continue
        rascunho = _ultimo(modelo, nota, status="RASCUNHO")
        if rascunho is None:
            faltas.append(f"{nome} da competência")
        elif chave == "relatorio" and not rascunho.conteudo.strip():
            faltas.append("relatório de atividades sem conteúdo (complete na tela)")
        elif chave == "planilha" and not rascunho.itens.exists():
            faltas.append("planilha de custos sem itens (complete na tela)")
        else:
            docs[chave] = rascunho
            rascunhos[chave] = {"pk": str(rascunho.pk), "atualizado_em": rascunho.atualizado_em.isoformat()}
    try:
        certidoes = certidoes_validas(contrato)
    except ValidationError as erro:
        certidoes = []
        faltas.extend(erro.messages)
    return {"docs": docs, "rascunhos": rascunhos, "faltas": faltas, "certidoes": certidoes,
            "enviados": [d for t, d in enviados.items() if t != "CONTRATO" and not (
                (t == "RELATORIO_ATIVIDADES" and "relatorio" in docs) or (t == "PLANILHA_CUSTOS" and "planilha" in docs)
                or (t == "RELATORIO_SLA" and "sla" in docs))]}


def frase_anexos(estado):
    partes = ["DANFSe"]
    nomes = {"relatorio": "relatório de atividades", "planilha": "demonstrativo de custos",
             "sla": "relatório de nível de serviço (SLA)"}
    partes += [nomes[c] for c in ("relatorio", "planilha", "sla") if c in estado["docs"]]
    partes += [d.titulo for d in estado["enviados"]]
    lista = ", ".join(partes[:-1]) + " e " + partes[-1] if len(partes) > 1 else partes[0]
    return f"{lista}, assinados digitalmente (ICP-Brasil), e certidões de regularidade fiscal e trabalhista vigentes"


def _pdf_previa(chave, doc):
    if chave == "relatorio":
        from apps.operacao.relatorios import previa_pdf

        return previa_pdf(doc)
    if chave == "planilha":
        from apps.financeiro.services.custos import pdf_planilha

        return pdf_planilha(doc, previa=True)
    from apps.sla.services.relatorio import apurar

    doc.dados = apurar(doc.contrato, doc.competencia, doc.dados.get("manuais"))
    doc.save(update_fields=["dados", "atualizado_em"])
    return renderizar_pdf("pdf/relatorio_sla.html", {"relatorio": doc, "dados": doc.dados, "empresa": doc.empresa,
                                                     "previa": True})


def anexos_previa(confirmacao, nota, estado):
    """Anexos (core.Anexo) mostrados no WhatsApp, na ordem do e-mail."""
    from .pdf_nfse import garantir_pdf

    competencia = f"{nota.competencia:%Y%m}"
    anexos = [garantir_pdf(nota)]
    titulos = {"relatorio": "relatorio_atividades", "planilha": "demonstrativo_custos", "sla": "relatorio_sla"}
    for chave in ("relatorio", "planilha", "sla"):
        doc = estado["docs"].get(chave)
        if doc is None:
            continue
        if chave in estado["rascunhos"]:
            anexos.append(Anexo.criar(confirmacao, f"PREVIA_{titulos[chave]}_{competencia}.pdf", _pdf_previa(chave, doc),
                                      descricao="Prévia para confirmação no WhatsApp", retencao_anos=1))
        else:
            anexos.append(doc.pdf)
    anexos += [d.anexo for d in estado["enviados"]]
    for indice, cert in enumerate(estado["certidoes"], 1):
        with cert.arquivo.open("rb") as f:
            dados = f.read(15_000_001)
        anexos.append(Anexo.criar(confirmacao, f"certidao_{indice:02d}_{slugify(cert.tipo.nome)[:60]}.pdf", dados,
                                  descricao="Cópia para confirmação no WhatsApp", retencao_anos=1))
    return anexos


# ---------------------------------------------------------------------------
# Proposta (WhatsApp)
# ---------------------------------------------------------------------------

def reverse_entregas(nota):
    from django.urls import reverse

    return reverse("fiscal:entregas", args=[nota.pk])


def link_entregas(nota):
    from django.conf import settings

    return settings.SITE_URL.rstrip("/") + reverse_entregas(nota)


def _avisar_faltas(ciclo, nota, faltas):
    from apps.core.services.notificacoes import notificar_papeis
    from apps.mensageria.services.fila import config_de, para_admins

    assinatura = hashlib.sha1("|".join(faltas).encode()).hexdigest()[:10]
    texto = (f"NFS-e {nota.numero_nfse} ({nota.contrato.numero}, {nota.competencia:%m/%Y}) autorizada. Para enviar os "
             "documentos ao órgão, falta: " + "; ".join(faltas) + ".")
    notificar_papeis(["Fiscal", "Financeiro"], "Envio de documentos pendente", texto, nivel="warning",
                     empresa=nota.empresa, link=reverse_entregas(nota), chave_dedup=f"envio-docs:{nota.pk}:{assinatura}",
                     janela_dedup_horas=24 * 30)
    config = config_de(nota.empresa)
    if config.ativo and config.avisos_faturamento:
        para_admins(nota.empresa, f"📄 *Envio de documentos pendente*\n{texto}\nAssim que estiver pronto, mando o e-mail "
                                  "aqui para sua confirmação.\n" + link_entregas(nota), chave=f"envio-docs-falta:{nota.pk}:{assinatura}")


def _ja_proposto(nota, agora):
    from apps.mensageria.models import Confirmacao

    c = Confirmacao.objects.filter(empresa=nota.empresa, acao=ACAO, objeto_id=str(nota.pk))
    St = Confirmacao.Status
    return c.filter(status__in=[St.PENDENTE, St.CONFIRMADA, St.RECUSADA]).exists() \
        or c.filter(status=St.EXPIRADA, expira_em__gte=agora - timedelta(hours=24)).exists()


def propor(ciclo, agora=None):
    """Monta o e-mail e pede a confirmação no WhatsApp. Retorna a Confirmacao criada ou None."""
    from apps.faturamento.services.ciclos import variaveis
    from apps.mensageria.services import confirmacoes
    from apps.mensageria.services.fila import config_de, para_admins

    from .entregas import emails

    agora = agora or timezone.now()
    agenda, nota = ciclo.agenda, ciclo.nota
    if not (agenda.enviar_email and nota and nota.status == NotaFiscal.Status.AUTORIZADA and nota.ambiente == 1
            and nota.contrato_id) or nota.entregas.exists() or _ja_proposto(nota, agora):
        return None
    config = config_de(nota.empresa)
    if not (config.ativo and config.admins and config.avisos_faturamento):
        return None
    garantir_rascunhos(ciclo)
    estado = levantar(nota)
    faltas = list(estado["faltas"])
    try:
        destinos = emails(agenda.emails_envio or "")
    except ValidationError:
        destinos = []
        faltas.append("destinatários do e-mail na agenda de faturamento")
    campos = {**variaveis(ciclo), "nota": nota.numero_nfse, "anexos": frase_anexos(estado),
              "empresa": nota.empresa.razao_social, "cnpj": nota.empresa.cnpj_formatado, "valor": brl(nota.valor_servicos)}
    try:
        assunto = re.sub(r"\s+", " ", (agenda.assunto_envio or "NFS-e {nota} — Contrato nº {contrato}").format(**campos)).strip()[:200]
        mensagem = (agenda.mensagem_envio or "").format(**campos).strip()
    except (KeyError, IndexError, ValueError) as erro:
        assunto = mensagem = ""
        faltas.append(f"modelo do e-mail inválido na agenda ({erro})")
    if not mensagem and not faltas:
        faltas.append("texto do e-mail na agenda de faturamento")
    if faltas:
        _avisar_faltas(ciclo, nota, faltas)
        return None
    c = confirmacoes.criar(nota.empresa, ACAO, nota, f"Enviar documentos da NFS-e {nota.numero_nfse} para "
                           + ", ".join(destinos), horas=PRAZO_HORAS,
                           dados={"nota": str(nota.pk), "ciclo": str(ciclo.pk), "destinatarios": destinos,
                                  "assunto": assunto, "mensagem": mensagem, "rascunhos": estado["rascunhos"]})
    anexos = anexos_previa(c, nota, estado)
    nomes_rascunho = {"relatorio": "relatório de atividades", "planilha": "planilha de custos", "sla": "relatório de SLA"}
    aprovar = [nomes_rascunho[k] for k in estado["rascunhos"]]
    corpo = mensagem if len(mensagem) <= 2500 else mensagem[:2500] + "… (texto completo na tela da nota)"
    linhas_anexos = "\n".join(f"• {a.nome}" for a in anexos)
    texto = (f"📧 *Confirme o envio dos documentos*\n{nota.contrato.numero} · {nota.tomador} · competência "
             f"{nota.competencia:%m/%Y}\nNFS-e {nota.numero_nfse} · {brl(nota.valor_servicos)}\n\n"
             f"*Para:* {', '.join(destinos)}\n*Assunto:* {assunto}\n\n————\n{corpo}\n————\n\n"
             f"*Anexos ({len(anexos)} PDFs, abaixo):*\n{linhas_anexos}\n"
             + (f"\n_PRÉVIA = rascunho; ao confirmar, {', '.join(aprovar)} são aprovados e assinados exatamente como "
                "estão. O e-mail leva também o índice do pacote._\n" if aprovar else
                "\n_O e-mail leva também o índice do pacote, assinado._\n")
             + f"\nResponda *SIM {c.codigo}* para {'aprovar e ' if aprovar else ''}enviar o e-mail, ou *NAO {c.codigo}* "
             f"para não enviar.\nPrazo: {timezone.localtime(c.expira_em):%d/%m %H:%M}.")
    para_admins(nota.empresa, texto, anexos, chave=f"envio-docs:{c.pk}")
    _registrar(ciclo, "envio_proposto", f"E-mail para {', '.join(destinos)} enviado ao WhatsApp para confirmação "
                                        f"(código {c.codigo}).")
    return c


def _registrar(ciclo, tipo, texto):
    from django.db import transaction

    from apps.faturamento.models import CicloFaturamento

    with transaction.atomic():
        atual = CicloFaturamento.objects.select_for_update().filter(pk=getattr(ciclo, "pk", ciclo)).first()
        if atual:
            atual.registrar(tipo, texto)
            atual.save()


def propor_pendentes(agora=None):
    """Rotina: propõe o envio das notas autorizadas recentes cujas agendas enviam por e-mail."""
    from apps.faturamento.models import CicloFaturamento

    agora = agora or timezone.now()
    total = 0
    ciclos = CicloFaturamento.objects.filter(status=CicloFaturamento.Status.AUTORIZADO, agenda__enviar_email=True,
                                             nota__status=NotaFiscal.Status.AUTORIZADA,
                                             nota__autorizada_em__gte=agora - timedelta(days=JANELA_DIAS)) \
        .select_related("agenda__contrato", "nota__contrato", "nota__tomador", "nota__empresa")
    for ciclo in ciclos:
        try:
            total += 1 if propor(ciclo, agora) else 0
        except Exception:  # noqa: BLE001 — uma nota com problema não impede as demais
            log.exception("proposta de envio de documentos falhou (ciclo %s)", ciclo.pk)
    return total


# ---------------------------------------------------------------------------
# Resposta
# ---------------------------------------------------------------------------

def responder(confirmacao, aceitar, por):
    dados = confirmacao.dados
    if not aceitar:
        _registrar(dados.get("ciclo"), "envio_recusado", f"Envio dos documentos não autorizado via {por}.")
        return "Ok, não enviei. Os documentos seguem como estão; você pode enviar pela tela da nota."
    from django.db import transaction

    from ..tasks import executar_envio_documentos

    transaction.on_commit(lambda: executar_envio_documentos.delay(str(confirmacao.pk)))
    return (f"Confirmado. {'Aprovando e assinando os documentos, ' if dados.get('rascunhos') else ''}gerando o pacote e "
            f"enviando para {', '.join(dados.get('destinatarios', []))}. Aviso aqui quando concluir.")


def usuario_whatsapp(empresa, por=""):
    """Usuário Administrador que responde pelo WhatsApp: o de mesmo telefone ou, na falta, o último a entrar."""
    from apps.core.models import Usuario

    admins = Usuario.objects.filter(empresa=empresa, is_active=True, groups__name="Administrador").distinct()
    numero = re.sub(r"\D", "", por or "")[-8:]
    if numero:
        for u in admins:
            if re.sub(r"\D", "", u.telefone or "").endswith(numero):
                return u
    return admins.exclude(email__endswith=".local").order_by("-last_login").first() or admins.first()


def aprovar_rascunhos(rascunhos, usuario):
    """Aprova (e assina) os rascunhos mostrados na prévia. Recusa se algum foi alterado depois dela."""
    from apps.financeiro.models import PlanilhaCustos
    from apps.financeiro.services.custos import PARAMETROS, salvar_planilha
    from apps.operacao.models import RelatorioAtividades
    from apps.operacao.relatorios import salvar_relatorio
    from apps.sla.models import RelatorioSLA
    from apps.sla.services import relatorio as sla

    if usuario is None:
        raise ValidationError("Nenhum usuário Administrador ativo para registrar a aprovação.")
    modelos = {"relatorio": RelatorioAtividades, "planilha": PlanilhaCustos, "sla": RelatorioSLA}
    nomes = {"relatorio": "relatório de atividades", "planilha": "planilha de custos", "sla": "relatório de SLA"}
    alvos = []
    for chave, info in rascunhos.items():
        doc = modelos[chave].objects.filter(pk=info["pk"]).first()
        if doc is None or (doc.status == "RASCUNHO" and chave != "sla" and doc.atualizado_em.isoformat() != info["atualizado_em"]):
            raise ValidationError(f"O {nomes[chave]} foi alterado depois da prévia. Confira e envie pela tela da nota.")
        if modelos[chave].objects.filter(contrato=doc.contrato, competencia=doc.competencia, versao__gt=doc.versao).exists():
            raise ValidationError(f"Há versão mais nova do {nomes[chave]}. Confira e envie pela tela da nota.")
        if doc.status == "RASCUNHO":
            alvos.append((chave, doc))
    for chave, doc in alvos:
        if chave == "relatorio":
            salvar_relatorio(doc, {c: getattr(doc, c) for c in ("introducao", "conteudo", "consideracoes_finais")},
                             usuario, aprovar=True)
        elif chave == "planilha":
            linhas = [{f: getattr(i, f) for f in ("grupo", "descricao", "unidade", "quantidade", "valor_unitario",
                                                  "rateio_pct", "periodicidade", "fonte")}
                      for i in doc.itens.order_by("criado_em", "pk")]
            salvar_planilha(doc, {c: getattr(doc, c) for c in (*PARAMETROS, "observacoes")}, linhas, usuario, aprovar=True)
        else:
            sla.aprovar(doc, usuario, doc.observacoes)
    return [c for c, _ in alvos]


def executar(confirmacao_pk):
    """Após o SIM: aprova os rascunhos, prepara o pacote, envia o e-mail e responde no WhatsApp."""
    from apps.core.travas import TravaOcupada, trava
    from apps.mensageria.models import Confirmacao
    from apps.mensageria.services.fila import para_admins

    from .entregas import enviar_entrega, preparar_entrega

    c = Confirmacao.objects.filter(pk=confirmacao_pk, acao=ACAO).first()
    if c is None or c.status != Confirmacao.Status.CONFIRMADA:
        return None
    dados = c.dados
    nota = NotaFiscal.objects.select_related("contrato", "empresa").get(pk=dados["nota"])
    try:
        with trava(f"envio-docs:{nota.pk}", ttl=600):
            if nota.entregas.exclude(status="PREPARADA").exists():
                raise ValidationError("Esta nota já tem um envio de documentos iniciado. Confira na tela da nota.")
            aprovados = aprovar_rascunhos(dados.get("rascunhos") or {}, usuario_whatsapp(nota.empresa, c.respondida_por))
            entrega = preparar_entrega(nota, "; ".join(dados["destinatarios"]), dados["assunto"], dados["mensagem"])
            entrega = enviar_entrega(entrega)
        from .entregas import anexos_email

        qtd = len(anexos_email(entrega.pacote.ler()))
        resultado = f"E-mail enviado ({entrega.get_status_display().lower()})."
        texto = (f"📨 *E-mail enviado* · NFS-e {nota.numero_nfse}\nPara: {', '.join(dados['destinatarios'])}\n"
                 f"{qtd} PDF(s) anexados" + (f"; aprovados e assinados: {', '.join(aprovados)}" if aprovados else "")
                 + ".\nRespostas do órgão aparecem em E-mails enviados.")
    except TravaOcupada:
        resultado = texto = "⏳ Este envio já está sendo processado."
    except (ValidationError, PermissionDenied, OSError) as erro:
        motivo = "; ".join(erro.messages) if isinstance(erro, ValidationError) else (str(erro) or "sem permissão")
        resultado = f"Não enviado: {motivo}"
        texto = (f"⚠️ *E-mail não enviado* · NFS-e {nota.numero_nfse}\n{motivo}\n"
                 f"Confira e envie pela tela da nota: {link_entregas(nota)}")
    Confirmacao.objects.filter(pk=c.pk).update(resultado=resultado[:300])
    _registrar(dados.get("ciclo"), "envio_documentos", resultado)
    para_admins(nota.empresa, texto, chave=f"envio-docs:{c.pk}:resultado")
    return resultado
