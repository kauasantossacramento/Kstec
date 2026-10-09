"""Configurações base do KS CENTRAL (compartilhadas por dev, test e prod)."""

from pathlib import Path

import environ
import structlog
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    NFSE_AMBIENTE=(str, "PRODUCAO_RESTRITA"),
)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-inseguro-troque-em-producao")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]
THIRD_PARTY_APPS = [
    "django_celery_beat",
    "simple_history",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "axes",
]
LOCAL_APPS = [
    "apps.core",
    "apps.cadastros",
    "apps.certidoes",
    "apps.contratos",
    "apps.catalogo",
    "apps.comercial",
    "apps.fiscal",
    "apps.financeiro",
    "apps.operacao",
    "apps.painel",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "apps.core.middleware.EmpresaMiddleware",
    "apps.core.middleware.MFAObrigatorioMiddleware",
    "apps.core.middleware.CSPMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.globais",
            ],
            "builtins": ["apps.core.templatetags.ks"],
        },
    }
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://kscentral:kscentral@localhost:5432/kscentral")
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.Usuario"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "painel:home"
LOGOUT_REDIRECT_URL = "core:login"

# Sessões de 8h (seção 12)
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_HTTPONLY = True

# Internacionalização (seção 0 e Fase 0)
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Bahia"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

STORAGE_BACKEND = env("STORAGE_BACKEND", default="local")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if STORAGE_BACKEND == "s3":
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("AWS_STORAGE_BUCKET_NAME", default="kscentral"),
            "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=None),
            "access_key": env("AWS_ACCESS_KEY_ID", default=None),
            "secret_key": env("AWS_SECRET_ACCESS_KEY", default=None),
            "default_acl": "private",
            "querystring_auth": True,
            "file_overwrite": False,
        },
    }

# Cache / Redis
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}

# Celery (Fase 0) — agenda conforme anexo 14.3
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    "sla.despachar_verificacoes": {"task": "apps.sla.tasks.despachar_verificacoes", "schedule": 60.0},
    "sla.agregar_dia": {"task": "apps.sla.tasks.agregar_dia", "schedule": crontab(hour=0, minute=15)},
    "sla.limpar_brutos": {"task": "apps.sla.tasks.limpar_brutos", "schedule": crontab(hour=3, minute=0)},
    "sla.verificar_ssl_todos": {"task": "apps.sla.tasks.verificar_ssl_todos", "schedule": crontab(hour=6, minute=0)},
    "certidoes.alertar_vencimentos": {
        "task": "apps.certidoes.tasks.alertar_vencimentos",
        "schedule": crontab(hour=7, minute=0),
    },
    "fiscal.alertar_certificado": {
        "task": "apps.fiscal.tasks.alertar_certificado",
        "schedule": crontab(hour=7, minute=5),
    },
    "fiscal.criar_guias_iss": {
        "task": "apps.fiscal.tasks.criar_guias_iss",
        "schedule": crontab(day_of_month=1, hour=8, minute=0),
    },
    "fiscal.verificar_adn": {"task": "apps.fiscal.tasks.verificar_notas_el_no_adn", "schedule": crontab(minute=20)},
    "contratos.alertar_vigencia_saldo": {
        "task": "apps.contratos.tasks.alertar_vigencia_saldo",
        "schedule": crontab(hour=7, minute=10),
    },
    "financeiro.marcar_atrasados": {
        "task": "apps.financeiro.tasks.marcar_atrasados",
        "schedule": crontab(hour=0, minute=30),
    },
    "financeiro.gerar_recorrencias": {
        "task": "apps.financeiro.tasks.gerar_recorrencias",
        "schedule": crontab(hour=0, minute=35),
    },
    "comercial.expirar_orcamentos": {
        "task": "apps.comercial.tasks.expirar_orcamentos",
        "schedule": crontab(hour=9, minute=0),
    },
    "comercial.followup": {"task": "apps.comercial.tasks.followup", "schedule": crontab(hour=9, minute=5)},
    "relatorios.lembrete_competencia": {
        "task": "apps.relatorios.tasks.lembrete_competencia",
        "schedule": crontab(day_of_month=1, hour=9, minute=0),
    },
    "ia.verificar_limite_custo": {"task": "apps.ia.tasks.verificar_limite_custo", "schedule": crontab(hour=8, minute=0)},
    "core.lembrete_teste_restauracao": {
        "task": "apps.core.tasks.lembrete_teste_restauracao",
        "schedule": crontab(day_of_month=5, hour=8, minute=30),
    },
}

# E-mail
EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="KS TEC <nao-responda@kstec.online>")

# Segredos (Fernet) — seção 3.3
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")

# IA
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
GEMINI_MODEL = env("GEMINI_MODEL", default="gemini-flash-latest")

# Fiscal
NFSE_AMBIENTE = env("NFSE_AMBIENTE")

# URL pública (links de orçamento, status page)
SITE_URL = env("SITE_URL", default="http://localhost:8000")

# django-axes (força bruta)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # horas
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_USERNAME_FORM_FIELD = "username"

# Papéis com MFA obrigatório (seção 12)
MFA_PAPEIS_OBRIGATORIOS = ["Administrador", "Financeiro", "Fiscal"]
MFA_OBRIGATORIO = env.bool("MFA_OBRIGATORIO", default=True)

# Logs JSON (structlog)
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processor": structlog.processors.JSONRenderer(ensure_ascii=False),
            "foreign_pre_chain": [
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
            ],
        },
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING"}, "axes": {"level": "WARNING"},
        # A API municipal exige token na query string: não registrar URLs HTTP em INFO/DEBUG.
        "httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"},
    },
}

# Sentry
SENTRY_DSN = env("SENTRY_DSN", default="")
