"""Configurações de desenvolvimento local."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["*"]
MFA_OBRIGATORIO = env.bool("MFA_OBRIGATORIO", default=False)
STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}  # noqa: F405
