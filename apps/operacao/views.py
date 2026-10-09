from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.crud import Coluna, CriarGenerico, Crud, DetalheGenerico, EditarGenerico
from apps.core.permissoes import exigir_escrita

from . import services
from .forms import ApontamentoForm, TarefaForm
from .models import Tarefa


class TarefaCrud(Crud):
    def queryset(self, request):
        return services.visiveis(request.user, request.empresa).select_related("contrato", "responsavel")


crud = TarefaCrud(Tarefa, "tarefa", "operacao", [Coluna("Título", "titulo", link=True), Coluna("Contrato", "contrato"),
    Coluna("Responsável", "responsavel"), Coluna("Prazo", "prazo", "data"), Coluna("Situação", "status")],
    feminino=True, caminho="tarefas", form_class=TarefaForm, papeis_escrita=["Operação"],
    busca=["titulo", "descricao", "protocolo_cliente"], filtros=["status", "tipo", "prioridade"],
    template_lista="operacao/lista.html", template_detalhe="operacao/detalhe.html")


class Persistir:
    def form_valid(self, form):
        try:
            self.object = services.salvar(form.save(commit=False), self.request.user)
        except ValidationError as erro:
            form.add_error(None, erro)
            return self.form_invalid(form)
        messages.success(self.request, "Tarefa salva.")
        return HttpResponseRedirect(self.get_success_url())


class CriarTarefa(Persistir, CriarGenerico):
    pass


class EditarTarefa(Persistir, EditarGenerico):
    pass


class DetalheTarefa(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = self.object
        if obj.status in ("CONCLUIDA", "CANCELADA"):
            ctx["url_editar"] = None
        ctx.update({"transicoes": [(s, Tarefa.Status(s).label) for s in services.TRANSICOES[obj.status]],
                    "apontamentos": obj.apontamentos.select_related("usuario"),
                    "total_horas": obj.apontamentos.aggregate(v=Sum("horas"))["v"] or 0,
                    "form_horas": ApontamentoForm(), "aberta": obj.status not in ("CONCLUIDA", "CANCELADA")})
        return ctx


@login_required
@require_POST
def status(request, pk):
    exigir_escrita(request.user, ["Operação"])
    obj = get_object_or_404(services.visiveis(request.user, request.empresa), pk=pk)
    try:
        services.transicionar(obj, request.POST.get("status"), request.user)
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
    else:
        messages.success(request, "Situação atualizada.")
    return redirect("operacao:tarefa_detalhe", pk=pk)


@login_required
@require_POST
def apontar(request, pk):
    exigir_escrita(request.user, ["Operação"])
    obj = get_object_or_404(services.visiveis(request.user, request.empresa), pk=pk)
    form = ApontamentoForm(request.POST)
    if form.is_valid():
        try:
            services.apontar(obj, request.user, **form.cleaned_data)
        except ValidationError as erro:
            form.add_error(None, erro)
        else:
            messages.success(request, "Horas registradas.")
            return redirect("operacao:tarefa_detalhe", pk=pk)
    messages.error(request, " ".join(str(erro) for erros in form.errors.values() for erro in erros))
    return redirect("operacao:tarefa_detalhe", pk=pk)


@login_required
def kanban(request):
    qs = services.visiveis(request.user, request.empresa).select_related("contrato", "responsavel")
    contrato = request.GET.get("contrato", "")
    if contrato:
        from apps.contratos.models import Contrato
        from apps.contratos.views import contratos_visiveis
        try:
            contrato_obj = get_object_or_404(contratos_visiveis(request.user, Contrato.objects.filter(empresa=request.empresa)), pk=contrato)
        except ValidationError:
            return HttpResponse("Informe um contrato válido.", status=400)
        qs = qs.filter(contrato=contrato_obj)
    colunas = [{"nome": nome, "tarefas": qs.filter(status=valor)} for valor, nome in Tarefa.Status.choices]
    return render(request, "operacao/kanban.html", {"colunas": colunas})
