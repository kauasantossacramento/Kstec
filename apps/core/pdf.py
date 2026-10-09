"""Geração de PDF com WeasyPrint a partir de templates HTML (relatórios, orçamentos, índices)."""

import hashlib

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string


def caminho_static(rel: str) -> str:
    achado = finders.find(rel)
    return f"file://{achado}" if achado else ""


def renderizar_pdf(template: str, contexto: dict) -> bytes:
    from weasyprint import HTML

    ctx = {"logo": caminho_static("img/ks-tec-logo.svg"), "SITE_URL": settings.SITE_URL, **contexto}
    html = render_to_string(template, ctx)
    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()
