"""Configurações para a suíte de testes (pytest)."""

from .base import *  # noqa: F401,F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
FIELD_ENCRYPTION_KEY = "rG4bDy3m6hW3J1lJ0x3hqS7c3YkJ8xV0pQ2sT5uX9zA="
MFA_OBRIGATORIO = False
AXES_ENABLED = False
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
MEDIA_ROOT = "/tmp/kscentral-test-media"
LOGGING = {"version": 1, "disable_existing_loggers": False}
