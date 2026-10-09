"""CRUD genérico com o design system: lista (busca, filtros, paginação HTMX), detalhe, criação e edição.

Cada módulo declara um `Crud` e chama `crud.urls()`; telas especiais sobrescrevem templates ou views.
"""

from dataclasses import dataclass, field

from django.contrib import messages
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from .forms import FormKS, campos_editaveis
from .models import Anexo
from .permissoes import PapelMixin, pode_escrever


@dataclass
class Coluna:
    rotulo: str
    campo: str
    tipo: str = "texto"  # texto | brl | data | datahora | status | doc | mono | bool | competencia | pct
    entidade: str | None = None
    link: bool = False


@dataclass
class Crud:
    model: type
    prefixo: str  # nome base das rotas, ex.: "pessoa"
    namespace: str
    colunas: list[Coluna]
    titulo: str = ""
    titulo_plural: str = ""
    subtitulo: str = ""
    form_class: type | None = None
    fields: list[str] | None = None
    busca: list[str] = field(default_factory=list)
    filtros: list[str] = field(default_factory=list)
    ordenacao: list[str] = field(default_factory=lambda: ["-criado_em"])
    papeis_escrita: list[str] | None = None
    papeis_leitura: list[str] | None = None
    template_lista: str = "crud/lista.html"
    template_detalhe: str = "crud/detalhe.html"
    template_form: str = "crud/form.html"
    nome_novo: str | None = None
    campos_detalhe: list[str] | None = None
    select_related: list[str] = field(default_factory=list)
    permitir_criar: bool = True
    permitir_editar: bool = True
    anexos: bool = True
    por_pagina: int = 25
    feminino: bool = False
    caminho: str = ""  # segmento de URL; padrão: prefixo + "s"
    conversor: str = "uuid"

    def __post_init__(self):
        meta = self.model._meta
        self.titulo = self.titulo or str(meta.verbose_name).capitalize()
        self.titulo_plural = self.titulo_plural or str(meta.verbose_name_plural).capitalize()
        self.nome_novo = self.nome_novo or f"{self.prefixo}_{'nova' if self.feminino else 'novo'}"
        if self.form_class is None:
            campos = self.fields or campos_editaveis(self.model)
            self.form_class = type(f"{self.model.__name__}Form", (FormKS,),
                                   {"Meta": type("Meta", (), {"model": self.model, "fields": campos})})

    # nomes de rota
    def rota(self, acao):
        nomes = {"lista": f"{self.prefixo}_lista", "novo": self.nome_novo, "detalhe": f"{self.prefixo}_detalhe",
                 "editar": f"{self.prefixo}_editar", "anexo": f"{self.prefixo}_anexo"}
        return f"{self.namespace}:{nomes[acao]}"

    def queryset(self, request):
        qs = self.model._default_manager.all()
        if hasattr(self.model, "empresa_id") and getattr(request, "empresa", None) is not None:
            qs = qs.filter(empresa=request.empresa)
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        return qs

    def urls(self, lista=None, novo=None, detalhe=None, editar=None):
        p = self.prefixo
        b = self.caminho or f"{p}s"
        cv = self.conversor
        return [
            path(f"{b}/", (lista or ListaGenerica).as_view(crud=self), name=f"{p}_lista"),
            path(f"{b}/novo/", (novo or CriarGenerico).as_view(crud=self), name=self.nome_novo),
            path(f"{b}/<{cv}:pk>/", (detalhe or DetalheGenerico).as_view(crud=self), name=f"{p}_detalhe"),
            path(f"{b}/<{cv}:pk>/editar/", (editar or EditarGenerico).as_view(crud=self), name=f"{p}_editar"),
            path(f"{b}/<{cv}:pk>/anexo/", AnexoUpload.as_view(crud=self), name=f"{p}_anexo"),
        ]


class CrudMixin(PapelMixin):
    crud: Crud = None

    def dispatch(self, request, *args, **kwargs):
        self.papeis_escrita = self.crud.papeis_escrita
        self.papeis_leitura = self.crud.papeis_leitura
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.crud.queryset(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.crud
        ctx.update({
            "crud": c,
            "pode_escrever": pode_escrever(self.request.user, c.papeis_escrita),
            "url_lista": reverse(c.rota("lista")),
            "url_novo": reverse(c.rota("novo")) if c.permitir_criar else None,
            "rota_detalhe": c.rota("detalhe"),
        })
        return ctx


class ListaGenerica(CrudMixin, ListView):
    def get_paginate_by(self, queryset):
        return self.crud.por_pagina

    def get_template_names(self):
        if self.request.headers.get("HX-Request") and self.request.GET.get("parcial") == "1":
            return ["components/data_table.html"]
        return [self.crud.template_lista]

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.crud.busca:
            cond = Q()
            for c in self.crud.busca:
                cond |= Q(**{f"{c}__icontains": q})
            qs = qs.filter(cond)
        for f in self.crud.filtros:
            v = self.request.GET.get(f)
            if v not in (None, ""):
                qs = qs.filter(**{f: v})
        ordem = self.request.GET.get("o")
        campos_ord = {c.campo.replace(".", "__") for c in self.crud.colunas}
        if ordem and ordem.lstrip("-") in campos_ord:
            qs = qs.order_by(ordem)
        else:
            qs = qs.order_by(*self.crud.ordenacao)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filtros = []
        for f in self.crud.filtros:
            try:
                campo = self.crud.model._meta.get_field(f.split("__")[0])
            except FieldDoesNotExist:
                continue
            escolhas = list(campo.choices or [])
            if not escolhas and campo.get_internal_type() == "BooleanField":
                escolhas = [("True", "Sim"), ("False", "Não")]
            filtros.append({"nome": f, "rotulo": str(campo.verbose_name).capitalize(), "escolhas": escolhas,
                            "atual": self.request.GET.get(f, "")})
        params = self.request.GET.copy()
        params.pop("page", None)
        params.pop("parcial", None)
        ctx.update({"filtros": filtros, "q": self.request.GET.get("q", ""), "querystring": params.urlencode(),
                    "ordem": self.request.GET.get("o", "")})
        return ctx


class DetalheGenerico(CrudMixin, DetailView):
    context_object_name = "obj"

    def get_template_names(self):
        return [self.crud.template_detalhe]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = self.object
        nomes = self.crud.campos_detalhe or list(self.crud.form_class.base_fields.keys())
        campos = []
        for n in nomes:
            try:
                f = obj._meta.get_field(n)
            except FieldDoesNotExist:
                continue
            if f.many_to_many:
                valor = ", ".join(str(x) for x in getattr(obj, n).all()) or "—"
            else:
                display = getattr(obj, f"get_{n}_display", None)
                valor = display() if callable(display) else getattr(obj, n)
            campos.append({"rotulo": str(f.verbose_name).capitalize(), "valor": valor,
                           "tipo": f.get_internal_type(), "nome": n})
        historico = []
        if hasattr(obj, "history"):
            registros = list(obj.history.all().select_related("history_user")[:20])
            for i, h in enumerate(registros):
                mudancas = []
                if i + 1 < len(registros) and h.history_type == "~":
                    try:
                        delta = h.diff_against(registros[i + 1])
                        mudancas = [
                            {"campo": c.field, "de": c.old, "para": c.new} for c in delta.changes
                            if c.field not in ("atualizado_em",)
                        ][:8]
                    except Exception:
                        mudancas = []
                historico.append({"data": h.history_date, "usuario": h.history_user, "tipo": h.history_type,
                                  "mudancas": mudancas})
        anexos = []
        if self.crud.anexos:
            from django.contrib.contenttypes.models import ContentType

            anexos = Anexo.objects.filter(content_type=ContentType.objects.get_for_model(obj), object_id=str(obj.pk))
        ctx.update({
            "campos": campos,
            "historico": historico,
            "anexos": anexos,
            "url_editar": reverse(self.crud.rota("editar"), args=[obj.pk]) if self.crud.permitir_editar else None,
            "url_anexo": reverse(self.crud.rota("anexo"), args=[obj.pk]),
        })
        return ctx


class _FormGenerico(CrudMixin):
    def get_form_class(self):
        return self.crud.form_class

    def get_template_names(self):
        return [self.crud.template_form]

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        if getattr(self.crud.form_class, "aceita_request", False):
            kw["request"] = self.request
        return kw

    def form_valid(self, form):
        obj = form.save(commit=False)
        if hasattr(obj, "empresa_id") and not obj.empresa_id:
            obj.empresa = self.request.empresa
        obj.save()
        form.save_m2m()
        self.object = obj
        messages.success(self.request, f"{self.crud.titulo} salvo com sucesso.")
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        destino = self.request.POST.get("_proximo")
        if destino and destino.startswith("/"):
            return destino
        return reverse(self.crud.rota("detalhe"), args=[self.object.pk])


class CriarGenerico(_FormGenerico, CreateView):
    def get_initial(self):
        ini = super().get_initial()
        for k, v in self.request.GET.items():
            if k in self.crud.form_class.base_fields:
                ini[k] = v
        return ini

    def dispatch(self, request, *args, **kwargs):
        if not self.crud.permitir_criar:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class EditarGenerico(_FormGenerico, UpdateView):
    def dispatch(self, request, *args, **kwargs):
        if not self.crud.permitir_editar:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class AnexoUpload(CrudMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(self.get_queryset(), pk=pk)
        arquivos = request.FILES.getlist("arquivo")
        for a in arquivos:
            Anexo.de_upload(obj, a, descricao=request.POST.get("descricao", ""))
        if arquivos:
            messages.success(request, f"{len(arquivos)} anexo(s) enviado(s).")
        return redirect(reverse(self.crud.rota("detalhe"), args=[pk]))
