"""Geração de PDF com WeasyPrint a partir de templates HTML (relatórios, orçamentos, índices)."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string


def caminho_static(rel: str) -> str:
    achado = finders.find(rel)
    return Path(achado).resolve().as_uri() if achado else ""


def renderizar_pdf(template: str, contexto: dict) -> bytes:
    ctx = {"logo": caminho_static("img/ks-tec-logo.png"), "SITE_URL": settings.SITE_URL, **contexto}
    html = render_to_string(template, ctx)
    executavel = getattr(settings, "WEASYPRINT_EXECUTABLE", "")
    if executavel:
        # O executável oficial isola as DLLs do Windows das bibliotecas de outros apps.
        with tempfile.TemporaryDirectory(prefix="kscentral-pdf-") as pasta:
            entrada = Path(pasta) / "entrada.html"
            saida = Path(pasta) / "saida.pdf"
            entrada.write_text(html, encoding="utf-8")
            subprocess.run(
                [executavel, "--base-url", Path(settings.BASE_DIR).as_uri() + "/", str(entrada), str(saida)],
                check=True, capture_output=True, timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return saida.read_bytes()
    from weasyprint import HTML

    return HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()
