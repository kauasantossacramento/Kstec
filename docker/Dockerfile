FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Bahia

# WeasyPrint (pango), xmlsec1 (verificação de assinaturas), cliente postgres (backup)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 libjpeg62-turbo \
        fonts-dejavu-core xmlsec1 postgresql-client curl tzdata libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 ks \
    && mkdir -p /app/media /app/staticfiles /app/data/whatsapp \
    && DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py collectstatic --noinput -v0 \
    && chown -R ks:ks /app
USER ks

EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-"]
