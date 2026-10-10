"""Filtros e tags do design system KS CENTRAL (formatação brasileira, badges, ícones, componentes)."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..status import cor_status
from ..validadores import formatar_cep, formatar_doc

register = template.Library()

# Ícones no estilo "Lucide" (traço 2px), desenhados para 24×24.
ICONES = {
    "home": '<path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    "file-text": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h6"/>',
    "users": '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3"/>',
    "receipt": '<path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "wallet": '<path d="M3 7a2 2 0 0 1 2-2h13v4"/><path d="M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2z"/><circle cx="16.5" cy="14.5" r="1.2"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
    "package": '<path d="m12 3 9 5v8l-9 5-9-5V8z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    "check-square": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 12 3 3 5-6"/>',
    "book": '<path d="M4 4h10a4 4 0 0 1 4 4v13H8a4 4 0 0 1-4-4z"/><path d="M4 17a4 4 0 0 1 4-4h10"/>',
    "calculator": '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M8 6h8M8 11h.01M12 11h.01M16 11h.01M8 15h.01M12 15h.01M16 15h.01M8 19h8"/>',
    "activity": '<path d="M3 12h4l3 8 4-16 3 8h4"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "more": '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "upload": '<path d="M12 21V9M7 14l5-5 5 5M5 3h14"/>',
    "send": '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
    "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "sparkles": '<path d="M12 3 13.8 8.2 19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "refresh": '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M3 21v-5h5"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "trending-up": '<path d="m3 17 6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
    "trending-down": '<path d="m3 7 6 6 4-4 8 8"/><path d="M14 17h7v-7"/>',
    "server": '<rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="13" width="18" height="8" rx="2"/><path d="M7 7h.01M7 17h.01"/>',
    "zip": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M10 3v2h2v2h-2v2h2v2h-2v3"/>',
    "repeat": '<path d="m17 2 4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
    "message": '<path d="M21 12a8.5 8.5 0 0 1-12.6 7.4L3 21l1.6-5.2A8.5 8.5 0 1 1 21 12z"/>',
    "credit-card": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
    "qr": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM20 14v.01M14 20h.01M17 20h4v-3"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "play": '<path d="m7 4 13 8-13 8z"/>',
    "skip": '<path d="m5 4 10 8-10 8zM19 5v14"/>',
    "zap": '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
    "smartphone": '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
}


@register.simple_tag
def icone(nome, tamanho=18, classe=""):
    path = ICONES.get(nome, ICONES["info"])
    return mark_safe(
        f'<svg class="ico {classe}" width="{tamanho}" height="{tamanho}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{path}</svg>'
    )


def _dec(valor):
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def formatar_numero(valor, casas=2):
    v = _dec(valor)
    if v is None:
        return ""
    q = Decimal(1).scaleb(-casas)
    s = f"{v.quantize(q):,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


@register.filter
def brl(valor):
    """R$ 1.234,56 (negativos como −R$ 1.234,56)."""
    v = _dec(valor)
    if v is None:
        return "—"
    s = formatar_numero(abs(v))
    return f"−R$ {s}" if v < 0 else f"R$ {s}"


@register.filter
def numero(valor, casas=2):
    return formatar_numero(valor, int(casas)) or "—"


@register.filter
def pct(valor, casas=1):
    s = formatar_numero(valor, int(casas))
    return f"{s}%" if s else "—"


@register.filter
def competencia(valor):
    if isinstance(valor, datetime | date):
        return f"{valor:%m/%Y}"
    return valor or "—"


@register.filter
def data_br(valor):
    if isinstance(valor, datetime):
        return f"{timezone.localtime(valor):%d/%m/%Y %H:%M}" if timezone.is_aware(valor) else f"{valor:%d/%m/%Y %H:%M}"
    if isinstance(valor, date):
        return f"{valor:%d/%m/%Y}"
    return valor or "—"


@register.filter
def doc(valor):
    return formatar_doc(valor) or "—"


@register.filter
def cep(valor):
    return formatar_cep(valor)


@register.filter
def attr(obj, nome):
    """Lê atributo/chave por nome (suporta 'a.b' e get_X_display)."""
    for parte in str(nome).split("."):
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(parte)
            continue
        display = getattr(obj, f"get_{parte}_display", None)
        obj = display() if callable(display) else getattr(obj, parte, None)
        if callable(obj) and not hasattr(obj, "all"):
            obj = obj()
    return obj


@register.filter
def get(dicionario, chave):
    return dicionario.get(chave) if isinstance(dicionario, dict) else None


@register.simple_tag
def status_badge(valor, entidade=None, rotulo=None):
    if valor in (None, ""):
        return "—"
    cor = cor_status(entidade, str(valor))
    texto = rotulo or str(valor).replace("_", " ").capitalize()
    return format_html('<span class="badge badge-{}"><span class="dot"></span>{}</span>', cor, texto)


@register.simple_tag
def badge_obj(obj, campo="status", entidade=None):
    if "." in campo:
        caminho, campo = campo.rsplit(".", 1)
        obj = attr(obj, caminho)
        if obj is None:
            return "—"
    valor = getattr(obj, campo, None)
    display = getattr(obj, f"get_{campo}_display", None)
    return status_badge(valor, entidade or obj.__class__.__name__, display() if callable(display) else None)


@register.inclusion_tag("components/kpi_card.html")
def kpi_card(rotulo, valor, variacao=None, formato="brl", alerta=False, icone_nome=None, link=None, serie=None):
    if formato == "brl":
        texto = brl(valor)
    elif formato == "pct":
        texto = pct(valor, 2)
    else:
        texto = valor if valor not in (None, "") else "—"
    var = _dec(variacao)
    return {"rotulo": rotulo, "valor": texto, "variacao": var, "alerta": alerta, "icone": icone_nome,
            "link": link, "serie": serie}


@register.inclusion_tag("components/empty_state.html")
def empty_state(frase, acao_url=None, acao_rotulo=None):
    return {"frase": frase, "acao_url": acao_url, "acao_rotulo": acao_rotulo}


@register.inclusion_tag("components/uptime_bar.html")
def uptime_bar(dias):
    """`dias`: lista de dicts {dia, pct} (até 90). pct None = sem dados."""
    barras = []
    for d in dias or []:
        p = d.get("pct")
        if p is None:
            cor = "none"
        elif p >= 99.5:
            cor = "ok"
        elif p >= 95:
            cor = "warn"
        else:
            cor = "bad"
        barras.append({"dia": d.get("dia"), "pct": p, "cor": cor})
    return {"barras": barras}


@register.filter
def dias_ate(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        valor = timezone.localtime(valor).date()
    return (valor - timezone.localdate()).days


@register.filter
def multiplicar(a, b):
    try:
        return Decimal(str(a)) * Decimal(str(b))
    except (InvalidOperation, ValueError):
        return ""


@register.filter
def nome_campo(model_ou_obj, campo):
    try:
        return model_ou_obj._meta.get_field(campo).verbose_name
    except Exception:
        return campo.replace("_", " ")


@register.filter
def duracao_curta(delta):
    """timedelta → "2 h 05 min" / "12 min"."""
    if not delta:
        return "—"
    minutos = int(delta.total_seconds() // 60)
    return f"{minutos // 60} h {minutos % 60:02d} min" if minutos >= 60 else f"{max(minutos, 1)} min"
