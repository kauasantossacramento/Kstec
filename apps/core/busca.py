"""Registro de modelos pesquisáveis pela busca global (Ctrl+K)."""

from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import Q


@dataclass
class Pesquisavel:
    rotulo: str
    model: type
    campos: list[str]
    titulo: Callable
    subtitulo: Callable
    url: Callable
    icone: str = "search"


REGISTRO: list[Pesquisavel] = []


def registrar(**kw):
    REGISTRO.append(Pesquisavel(**kw))


def buscar(termo: str, empresa, limite=6):
    termo = (termo or "").strip()
    if len(termo) < 2:
        return []
    grupos = []
    for p in REGISTRO:
        q = Q()
        for c in p.campos:
            q |= Q(**{f"{c}__icontains": termo})
        qs = p.model.objects.filter(q)
        if hasattr(p.model, "empresa"):
            qs = qs.filter(empresa=empresa)
        itens = [
            {"titulo": p.titulo(o), "subtitulo": p.subtitulo(o), "url": p.url(o)} for o in qs[:limite]
        ]
        if itens:
            grupos.append({"rotulo": p.rotulo, "icone": p.icone, "itens": itens})
    return grupos
