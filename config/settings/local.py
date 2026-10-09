"""Perfil de demonstração local, sem PostgreSQL ou Redis. Não usar em produção."""

from .dev import *  # noqa: F401,F403
from .dev import BASE_DIR

_pdf_exe = BASE_DIR / ".tools" / "weasyprint" / "onedir" / "weasyprint" / "weasyprint.exe"
WEASYPRINT_EXECUTABLE = str(_pdf_exe) if _pdf_exe.is_file() else ""

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "local.sqlite3"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
# EMAIL_URL define o SMTP como nos demais perfis; o envio real local é opt-in.
if not env.bool("KSCENTRAL_EMAIL_REAL", default=False):  # noqa: F405
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
MFA_OBRIGATORIO = False
