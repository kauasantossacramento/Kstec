"""Perfil de demonstração local, sem PostgreSQL ou Redis. Não usar em produção."""

from .dev import *  # noqa: F401,F403
from .dev import BASE_DIR

_pdf_exe = BASE_DIR / ".tools" / "weasyprint" / "onedir" / "weasyprint" / "weasyprint.exe"
WEASYPRINT_EXECUTABLE = str(_pdf_exe) if _pdf_exe.is_file() else ""

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "local.sqlite3"}}
# Redis local opcional (Memurai/WSL/Docker): KSCENTRAL_REDIS=True ativa cache, travas, worker e beat reais.
# Sem ele, as tarefas rodam de forma síncrona e as rotinas são acionadas pelos botões "Executar rotina agora".
if env.bool("KSCENTRAL_REDIS", default=False):  # noqa: F405
    REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")  # noqa: F405
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
    CELERY_BROKER_URL = CELERY_RESULT_BACKEND = REDIS_URL
    CELERY_TASK_ALWAYS_EAGER = False
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
# EMAIL_URL define o SMTP como nos demais perfis; o envio real local é opt-in.
EMAIL_CONTAS_SMTP = env.bool("KSCENTRAL_EMAIL_REAL", default=False)  # noqa: F405
if not env.bool("KSCENTRAL_EMAIL_REAL", default=False):  # noqa: F405
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
MFA_OBRIGATORIO = False
