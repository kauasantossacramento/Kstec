"""Endpoint /health usado por Docker, Caddy e monitoramento externo."""

import time

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def health(request):
    componentes = {}
    status = "ok"
    t0 = time.perf_counter()
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        componentes["banco"] = {"status": "ok", "latencia_ms": int((time.perf_counter() - t0) * 1000)}
    except Exception as e:  # pragma: no cover - depende de infra
        componentes["banco"] = {"status": "down", "detalhe": type(e).__name__}
        status = "down"
    try:
        cache.set("health", "1", 5)
        componentes["cache"] = {"status": "ok" if cache.get("health") == "1" else "degraded"}
    except Exception as e:  # pragma: no cover
        componentes["cache"] = {"status": "degraded", "detalhe": type(e).__name__}
        status = "degraded" if status == "ok" else status
    return JsonResponse({"status": status, "componentes": componentes}, status=200 if status != "down" else 503)
