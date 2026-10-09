"""Aplicação Celery do KS CENTRAL (worker + beat)."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("kscentral")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
