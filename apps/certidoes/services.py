"""Regras de certidões: extração de dados do PDF, semáforo de habilitação, alertas e kit ZIP."""

import io
import re
import zipfile
from datetime import date, datetime

from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.core.agenda import Evento, ItemAtencao, agenda, atencao
from apps.core.models import Anexo, Parametro
from apps.core.pdf import renderizar_pdf
from apps.core.services.notificacoes import notificar_papeis

from .models import Certidao, KitHabilitacao, TipoCertidao

RE_DATA = r"(\d{2}/\d{2}/\d{4})"
PADROES_VALIDADE = [
    re.compile(r"v[áa]lid[ao]\s+at[ée]\s*:?\s*" + RE_DATA, re.I),
    re.compile(r"validade\s*:?\s*" + RE_DATA, re.I),
    re.compile(r"v[áa]lida\s+por\s+\d+\s+dias.*?at[ée]\s*" + RE_DATA, re.I | re.S),
]
PADROES_CODIGO = [
    re.compile(r"c[óo]digo\s+de\s+controle\s+da\s+certid[ãa]o\s*:?\s*([A-Z0-9.\-]{6,})", re.I),
    re.compile(r"c[óo]digo\s+de\s+controle\s*:?\s*([A-Z0-9.\-]{6,})", re.I),
    re.compile(r"certid[ãa]o\s+n[ºo°.]*\s*:?\s*([0-9./\-]{5,})", re.I),
    re.compile(r"autentica[çc][ãa]o\s*:?\s*([A-Z0-9.\-]{6,})", re.I),
]
PADROES_EMISSAO = [
    re.compile(r"emitid[ao]\s+(?:às|as)\s+[\d:]+\s+do\s+dia\s+" + RE_DATA, re.I),
    re.compile(r"emiss[ãa]o\s*:?\s*" + RE_DATA, re.I),
    re.compile(r"emitid[ao]\s+em\s*:?\s*" + RE_DATA, re.I),
]


def _data(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def extrair_texto_pdf(conteudo: bytes) -> str:
    from pypdf import PdfReader

    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        return "\n".join((p.extract_text() or "") for p in leitor.pages[:3])
    except Exception:
        return ""


def extrair_dados(texto: str) -> dict:
    """Pré-preenche validade, emissão, código de controle e situação a partir do texto do PDF."""
    dados = {}
    for p in PADROES_VALIDADE:
        m = p.search(texto)
        if m and _data(m.group(1)):
            dados["data_validade"] = _data(m.group(1))
            break
    for p in PADROES_EMISSAO:
        m = p.search(texto)
        if m and _data(m.group(1)):
            dados["data_emissao"] = _data(m.group(1))
            break
    for p in PADROES_CODIGO:
        m = p.search(texto)
        if m:
            dados["numero"] = m.group(1).strip(" .")
            break
    t = texto.upper()
    if "POSITIVA COM EFEITO" in t or "POSITIVA COM EFEITOS" in t:
        dados["situacao"] = Certidao.Situacao.POSITIVA_COM_EFEITO_NEGATIVA
    elif "CERTIDÃO POSITIVA" in t or "CERTIDAO POSITIVA" in t:
        dados["situacao"] = Certidao.Situacao.POSITIVA
    elif "NEGATIVA" in t:
        dados["situacao"] = Certidao.Situacao.NEGATIVA
    return dados


def situacao_habilitacao(empresa) -> dict:
    """Semáforo por tipo obrigatório + indicador geral APTA / ATENCAO / INAPTA."""
    linhas = []
    for tipo in TipoCertidao.objects.filter(empresa=empresa, ativo=True).order_by("nome"):
        c = tipo.ultima
        status = c.status if c else "AUSENTE"
        if c and c.situacao == Certidao.Situacao.POSITIVA:
            status = "VENCIDA"  # positiva impede habilitação
        linhas.append({"tipo": tipo, "certidao": c, "status": status})
    obrig = [linha for linha in linhas if linha["tipo"].obrigatoria_habilitacao]
    if any(linha["status"] in ("VENCIDA", "AUSENTE") for linha in obrig):
        geral = "INAPTA"
    elif any(linha["status"] == "VENCENDO" for linha in obrig):
        geral = "ATENCAO"
    else:
        geral = "APTA"
    return {"geral": geral, "linhas": linhas}


def certidoes_pendentes_contrato(contrato) -> list[str]:
    """Tipos exigidos pelo contrato sem certidão vigente (usado no checklist de emissão da NF)."""
    pend = []
    for tipo in contrato.certidoes_exigidas.all():
        if tipo.vigente is None:
            pend.append(tipo.nome)
    return pend


def alertar_vencimentos() -> int:
    dias_alerta = set()
    total = 0
    hoje = timezone.localdate()
    for c in Certidao.objects.filter(ativo=True).select_related("tipo"):
        dias_alerta = set(Parametro.get("certidoes.dias_alerta", [30, 15, 7, 0], empresa=c.empresa))
        # só alerta a certidão mais recente de cada tipo
        if c.tipo.ultima != c:
            continue
        d = (c.data_validade - hoje).days
        if d in dias_alerta or d < 0 and d % 7 == 0:
            texto = "vence hoje" if d == 0 else (f"vence em {d} dias" if d > 0 else f"venceu há {-d} dias")
            total += len(notificar_papeis(
                ["Administrador", "Financeiro", "Fiscal"], f"Certidão {c.tipo.nome} {texto}",
                f"Validade: {c.data_validade:%d/%m/%Y}. Emita uma nova em {c.tipo.url_emissao or 'portal do órgão'}.",
                nivel="danger" if d <= 7 else "warning", link=reverse("certidoes:home"), email=True,
                chave_dedup=f"certidao-{c.pk}-{d}", empresa=c.empresa,
            ))
    return total


def gerar_kit(kit: KitHabilitacao) -> Anexo:
    """ZIP com as certidões + documentos extras + índice em PDF. Certidões vencidas ficam fora (com aviso)."""
    certs = list(kit.certidoes.select_related("tipo").order_by("tipo__nome"))
    avisos, incluidas = [], []
    for c in certs:
        if c.status == "VENCIDA":
            avisos.append(f"{c.tipo.nome} está vencida desde {c.data_validade:%d/%m/%Y} e NÃO foi incluída.")
        else:
            incluidas.append(c)
    from django.contrib.contenttypes.models import ContentType

    anexados = Anexo.objects.filter(content_type=ContentType.objects.get_for_model(kit), object_id=str(kit.pk))
    if kit.zip_id:
        anexados = anexados.exclude(pk=kit.zip_id).exclude(descricao="Kit de habilitação")
    extras = list(kit.documentos_extra.all()) + list(anexados.exclude(descricao="Kit de habilitação"))
    agora = timezone.now()
    indice = renderizar_pdf("pdf/kit_indice.html", {"kit": kit, "certidoes": certs, "extras": extras,
                                                     "avisos": avisos, "empresa": kit.empresa, "gerado_em": agora})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("00_indice.pdf", indice)
        for i, c in enumerate(incluidas, start=1):
            if c.arquivo:
                with c.arquivo.open("rb") as f:
                    z.writestr(f"{i:02d}_{slugify(c.tipo.nome)}.pdf", f.read())
        for j, a in enumerate(extras, start=len(incluidas) + 1):
            z.writestr(f"{j:02d}_{a.nome}", a.ler())
    anexo = Anexo.criar(kit, f"kit_{slugify(kit.nome)}.zip", buf.getvalue(), descricao="Kit de habilitação")
    kit.zip = anexo
    kit.gerado_em = agora
    kit.save(update_fields=["zip", "gerado_em"])
    kit.avisos = avisos
    return anexo


@agenda
def _agenda_certidoes(empresa, inicio, fim):
    eventos = []
    for c in Certidao.objects.filter(empresa=empresa, ativo=True, data_validade__range=(inicio, fim)).select_related("tipo"):
        if c.tipo.ultima == c:
            eventos.append(Evento(c.data_validade, f"Vence: {c.tipo.nome}", "CERTIDAO", reverse("certidoes:home"),
                                  "danger" if c.dias_restantes <= 7 else "warning"))
    return eventos


@atencao
def _atencao_certidoes(empresa, usuario):
    itens = []
    for linha in situacao_habilitacao(empresa)["linhas"]:
        if linha["status"] in ("VENCIDA", "VENCENDO") and linha["tipo"].obrigatoria_habilitacao:
            c = linha["certidao"]
            venc = linha["status"] == "VENCIDA"
            itens.append(ItemAtencao(
                f"Certidão {linha['tipo'].nome} {'vencida' if venc else 'vencendo'}",
                reverse("certidoes:home"), "danger" if venc else "warning", 10 if venc else 20,
                f"Validade {c.data_validade:%d/%m/%Y}" if c else "", "shield"))
    return itens
