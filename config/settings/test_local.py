"""Suíte local portátil; CI continua executando com PostgreSQL em settings.test."""

from .test import *  # noqa: F401,F403
from .test import BASE_DIR

_pdf_exe = BASE_DIR / ".tools" / "weasyprint" / "onedir" / "weasyprint" / "weasyprint.exe"
WEASYPRINT_EXECUTABLE = str(_pdf_exe) if _pdf_exe.is_file() else ""

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
MEDIA_ROOT = BASE_DIR / ".tools" / "test-media"
