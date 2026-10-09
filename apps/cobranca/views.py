import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.cadastros.models import Pessoa
from apps.core.crud import Coluna, Crud
from apps.core.permissoes import exigir_escrita, pode_escrever
from apps.financeiro.models import Lancamento

from .forms import ConfiguracaoAsaasForm, PerfilCobrancaForm
from .models import CobrancaAsaas, ConfiguracaoAsaas
from .services import cobrancas

PAPEIS = ["Financeiro", "Fiscal"]

crud = Crud(CobrancaAsaas, "cobranca", "cobranca", [
    Coluna("Lançamento", "lancamento", link=True), Coluna("Vencimento", "vencimento", "data"),
    Coluna("Valor", "valor", "brl"), Coluna("Forma", "forma"), Coluna("Situação", "status", "status", "CobrancaAsaas")],
    caminho="", feminino=True, permitir_criar=False, permitir_editar=False, papeis_leitura=PAPEIS,
    papeis_escrita=["Financeiro"], busca=["asaas_id", "lancamento__descricao", "lancamento__pessoa__razao_social"],
    filtros=["status", "ambiente"], select_related=["lancamento__pessoa"], titulo="Cobrança",
    titulo_plural="Cobranças (Asaas)", template_detalhe="cobranca/detalhe.html",
    subtitulo="Links de pagamento, boletos e PIX gerados pelo Asaas.")


def _leitura(request):
    if not request.user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        raise PermissionDenied


@login_required
def configuracao(request):
    _leitura(request)
    config = ConfiguracaoAsaas.objects.filter(empresa=request.empresa).first() or ConfiguracaoAsaas(empresa=request.empresa)
    form = ConfiguracaoAsaasForm(request.POST or None, instance=config)
    if request.method == "POST":
        exigir_escrita(request.user, ["Financeiro"])
        if request.POST.get("testar"):
            try:
                cobrancas.testar(cobrancas.configuracao(request.empresa))
            except ValidationError as erro:
                messages.error(request, "; ".join(erro.messages))
            else:
                messages.success(request, "Conexão com o Asaas confirmada.")
            return redirect("cobranca:configuracao")
        if form.is_valid():
            try:
                obj = form.save(commit=False)
                obj.empresa = request.empresa
                cobrancas.salvar_configuracao(obj, form.cleaned_data["nova_api_key"])
            except ValidationError as erro:
                form.add_error(None, erro)
            else:
                messages.success(request, "Configuração do Asaas salva. A chave fica cifrada.")
                return redirect("cobranca:configuracao")
    webhook_url = request.build_absolute_uri(reverse("cobranca:webhook"))
    return render(request, "cobranca/configuracao.html", {
        "form": form, "config": config, "webhook_url": webhook_url,
        "webhook_token": config.webhook_token.ler() if config.pk and config.webhook_token_id else "",
        "pode_salvar": pode_escrever(request.user, ["Financeiro"])})


@login_required
@require_POST
def gerar(request, lancamento_pk):
    exigir_escrita(request.user, ["Financeiro"])
    lancamento = get_object_or_404(Lancamento, pk=lancamento_pk, empresa=request.empresa)
    nota = lancamento.nota_fiscal
    try:
        cobranca = cobrancas.cobrar_lancamento(lancamento, request.POST.get("forma") or None, nota=nota)
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
        return redirect("financeiro:lancamento_detalhe", pk=lancamento.pk)
    messages.success(request, "Cobrança pronta: link e PIX disponíveis para envio.")
    return redirect("cobranca:cobranca_detalhe", pk=cobranca.pk)


@login_required
@require_POST
def atualizar(request, pk):
    exigir_escrita(request.user, ["Financeiro"])
    cobranca = get_object_or_404(CobrancaAsaas, pk=pk, empresa=request.empresa)
    try:
        cobrancas.sincronizar(cobranca)
    except ValidationError as erro:
        messages.error(request, "; ".join(erro.messages))
    else:
        messages.success(request, "Situação atualizada pelo Asaas.")
    return redirect("cobranca:cobranca_detalhe", pk=pk)


@login_required
def perfil(request, pessoa_pk):
    """Comunicação e cobrança do cliente: preferências, contatos de WhatsApp e consentimento."""
    _leitura(request)
    pessoa = get_object_or_404(Pessoa, pk=pessoa_pk, empresa=request.empresa)
    obj = cobrancas.perfil(pessoa)
    form = PerfilCobrancaForm(request.POST or None, instance=obj)
    from apps.mensageria.forms import ContatoForm
    from apps.mensageria.models import ContatoWhatsApp

    contato_form = ContatoForm(prefix="contato")
    if request.method == "POST":
        exigir_escrita(request.user, ["Financeiro", "Fiscal"])
        if form.is_valid():
            form.save()
            messages.success(request, "Preferências de cobrança salvas.")
            return redirect("cobranca:perfil", pessoa_pk=pessoa.pk)
    return render(request, "cobranca/perfil.html", {
        "pessoa": pessoa, "form": form, "contatos": ContatoWhatsApp.objects.filter(pessoa=pessoa),
        "contato_form": contato_form, "pode_escrever": pode_escrever(request.user, ["Financeiro", "Fiscal"]),
        "cobrancas": CobrancaAsaas.objects.filter(lancamento__pessoa=pessoa).select_related("lancamento")[:10]})


@csrf_exempt
@require_POST
def webhook(request):
    """Endpoint público do Asaas. Autenticado pelo cabeçalho asaas-access-token (comparação em tempo constante)."""
    config = cobrancas.config_por_token(request.headers.get("asaas-access-token", ""))
    if config is None:
        return HttpResponse(status=401)
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)
    from apps.core import contexto

    with contexto.usar_contexto(config.empresa):
        cobrancas.processar_webhook(config, payload)
    return JsonResponse({"recebido": True})
