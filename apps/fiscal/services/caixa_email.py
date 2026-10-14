"""Leitura (somente leitura, IMAP) da caixa que envia notas e documentos, vinculando cada mensagem recebida ao envio
de origem: respostas, avisos automáticos e devoluções (e-mail não entregue).

Vínculo, em ordem: cabeçalhos In-Reply-To/References com o Message-ID do envio → assunto (sem "Re:/RES:/ENC:") →
remetente que recebeu um envio antes. Mensagens sem relação com os envios (propaganda etc.) são ignoradas.
"""

import email
import hashlib
import html
import imaplib
import re
from datetime import timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from django.utils import timezone

from apps.core.models import ContaEmail

from ..models import EntregaNota, RespostaEmail

PREFIXOS = re.compile(r"^\s*((re|res|fw|fwd|enc|tr|aw|resp)\s*:\s*)+", re.IGNORECASE)
CITACAO = re.compile(r"\n\s*(Em .{5,120}escreveu:|On .{5,120}wrote:|-{2,}\s*Original Message|-{2,}\s*Mensagem original|De:\s.+\n\s*Enviad)", re.IGNORECASE)
AUTOMATICA = re.compile(r"gerada automaticamente|resposta autom[aá]tica|automatic reply|auto-?reply|n[aã]o h[aá] necessidade de respond", re.IGNORECASE)


def decodificar(valor):
    try:
        return str(make_header(decode_header(valor or "")))
    except Exception:  # noqa: BLE001
        return valor or ""


def normalizar_assunto(assunto):
    return " ".join(PREFIXOS.sub("", assunto or "").split()).lower()


def html_para_texto(conteudo):
    conteudo = re.sub(r"(?is)<(style|script).*?</\1>", " ", conteudo)
    conteudo = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", conteudo)
    return html.unescape(re.sub(r"<[^>]+>", " ", conteudo))


def corpo_e_anexos(msg):
    texto, alternativo, anexos, original = "", "", [], {}
    for parte in msg.walk():
        tipo = parte.get_content_type()
        if tipo in ("message/rfc822", "text/rfc822-headers"):
            interno = parte.get_payload(0) if tipo == "message/rfc822" else email.message_from_string(
                parte.get_payload(decode=True).decode("utf-8", "ignore"))
            original = {"assunto": decodificar(interno.get("Subject")), "message_id": (interno.get("Message-ID") or "").strip()}
            continue
        if parte.get_content_maintype() == "multipart":
            continue
        nome = parte.get_filename()
        if nome:
            anexos.append(decodificar(nome))
            continue
        try:
            dados = parte.get_payload(decode=True) or b""
            conteudo = dados.decode(parte.get_content_charset() or "utf-8", "ignore")
        except (LookupError, AttributeError):
            continue
        if tipo == "text/plain" and not texto:
            texto = conteudo
        elif tipo == "text/html" and not alternativo:
            alternativo = html_para_texto(conteudo)
    texto = texto or alternativo
    texto = CITACAO.split(texto)[0]
    texto = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", texto)).strip()
    return texto[:20000], anexos, original


def vincular(empresa, recebido_em, remetente, assunto, referencias, original):
    enviadas = EntregaNota.objects.filter(empresa=empresa, status="ENVIADA", enviado_em__lte=recebido_em + timedelta(minutes=5))
    ids = [r for r in referencias if r]
    if original.get("message_id"):
        ids.append(original["message_id"])
    if ids:
        e = enviadas.filter(message_id__in=ids).order_by("-enviado_em").first()
        if e:
            return e, "cabeçalho"
    alvo = normalizar_assunto(original.get("assunto") or assunto)
    if alvo:
        for e in enviadas.order_by("-enviado_em")[:500]:
            if normalizar_assunto(e.assunto) == alvo:
                return e, "assunto"
    if remetente:
        for e in enviadas.order_by("-enviado_em")[:500]:
            if remetente in [d.lower() for d in e.destinatarios]:
                return e, "remetente"
    return None, ""


def classificar(msg, remetente, assunto, texto):
    tipo_conteudo = msg.get_content_type()
    if remetente.startswith(("mailer-daemon", "postmaster")) or tipo_conteudo == "multipart/report" \
            or "undeliver" in assunto.lower() or "não entregue" in assunto.lower():
        return RespostaEmail.Tipo.DEVOLUCAO
    auto = (msg.get("Auto-Submitted") or "no").lower()
    if auto != "no" or AUTOMATICA.search(texto[:600]) or AUTOMATICA.search(assunto):
        return RespostaEmail.Tipo.AUTOMATICA
    return RespostaEmail.Tipo.RESPOSTA


def sincronizar(empresa, dias=45, imap=None):
    """Lê a caixa de entrada da conta de documentos e grava as mensagens vinculadas. Retorna quantas são novas."""
    conta = ContaEmail.objects.filter(empresa=empresa, finalidade="DOCUMENTOS", ativo=True).first()
    if conta is None or not conta.senha_id:
        return 0
    destinos = {d.lower() for lista in EntregaNota.objects.filter(empresa=empresa, status="ENVIADA")
                .values_list("destinatarios", flat=True) for d in lista}
    conhecidos = set(RespostaEmail.objects.filter(empresa=empresa).values_list("message_id", flat=True))
    cliente = imap or imaplib.IMAP4_SSL(conta.host.replace("smtp.", "imap.", 1), 993, timeout=30)
    novas = 0
    try:
        cliente.login(conta.usuario or conta.email, conta.senha.ler())
        cliente.select("INBOX", readonly=True)
        desde = (timezone.localdate() - timedelta(days=dias)).strftime("%d-%b-%Y")
        _tipo, ids = cliente.search(None, "SINCE", desde)
        for num in ids[0].split():
            _tipo, dados = cliente.fetch(num, "(BODY.PEEK[])")
            bruto = dados[0][1]
            msg = email.message_from_bytes(bruto)
            message_id = (msg.get("Message-ID") or "").strip() or "sem-id:" + hashlib.sha256(bruto).hexdigest()[:40]
            if message_id in conhecidos:
                continue
            nome, remetente = parseaddr(decodificar(msg.get("From")))
            remetente = remetente.lower()
            assunto = decodificar(msg.get("Subject"))
            try:
                recebido = parsedate_to_datetime(msg.get("Date"))
            except (TypeError, ValueError):
                recebido = timezone.now()
            if timezone.is_naive(recebido):
                recebido = timezone.make_aware(recebido)
            texto, anexos, original = corpo_e_anexos(msg)
            referencias = [r.strip() for r in re.findall(r"<[^>]+>", f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}")]
            entrega, vinculo = vincular(empresa, recebido, remetente, assunto, referencias, original)
            tipo = classificar(msg, remetente, assunto, texto)
            if entrega is None and remetente not in destinos:
                continue  # não tem relação com os envios
            RespostaEmail.objects.create(empresa=empresa, entrega=entrega, message_id=message_id[:250], tipo=tipo,
                                         remetente=remetente[:250], remetente_nome=nome[:250], assunto=assunto[:300],
                                         recebido_em=recebido, texto=texto, anexos=anexos, vinculo=vinculo)
            conhecidos.add(message_id)
            novas += 1
    finally:
        try:
            cliente.logout()
        except Exception:  # noqa: BLE001
            pass
    return novas

