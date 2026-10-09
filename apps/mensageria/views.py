from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.crud import Coluna, Crud
from apps.core.permissoes import exigir_escrita, pode_escrever

from .forms import ConfiguracaoWhatsAppForm, ContatoForm
from .models import Confirmacao, ContatoWhatsApp, LoteEnvio, MensagemWhatsApp
from .services import envios, fila, worker

PAPEIS = ["Financeiro", "Fiscal"]
M = MensagemWhatsApp

contatos = Crud(ContatoWhatsApp, "contato", "whatsapp", [
    Coluna("Nome", "nome", link=True), Coluna("Telefone", "telefone_formatado", "mono"), Coluna("Cliente", "pessoa"),
    Coluna("Consentimento", "consentimento", "bool"), Coluna("Notas", "recebe_notas", "bool"),
    Coluna("Cobranças", "recebe_cobrancas", "bool")], form_class=ContatoForm, caminho="contatos",
    papeis_escrita=PAPEIS, papeis_leitura=PAPEIS, busca=["nome", "telefone", "pessoa__razao_social"],
    filtros=["consentimento", "ativo"], select_related=["pessoa"], titulo="Contato de WhatsApp",
    titulo_plural="Contatos de WhatsApp", subtitulo="Somente contatos com consentimento registrado recebem mensagens.",
    campos_detalhe=["pessoa", "nome", "telefone", "consentimento", "consentimento_em", "origem_consentimento",
                    "recebe_notas", "recebe_cobrancas", "verificado", "descadastrado_em", "primeira_mensagem_em", "ativo"])

mensagens = Crud(MensagemWhatsApp, "mensagem", "whatsapp", [
    Coluna("Destino", "telefone_formatado", "mono", link=True), Coluna("Direção", "direcao"),
    Coluna("Texto", "texto"), Coluna("Arquivo", "nome_arquivo"), Coluna("Quando", "criado_em", "datahora"),
    Coluna("Situação", "status", "status", "MensagemWhatsApp")], caminho="mensagens", feminino=True,
    permitir_criar=False, permitir_editar=False, anexos=False, papeis_leitura=PAPEIS, papeis_escrita=PAPEIS,
    busca=["telefone", "texto", "nome_arquivo"], filtros=["status", "direcao", "para_admin"],
    select_related=["contato"], titulo="Mensagem", titulo_plural="Mensagens de WhatsApp",
    campos_detalhe=["direcao", "telefone", "contato", "lote", "para_admin", "tipo", "texto", "nome_arquivo", "status",
                    "agendada_para", "enviada_em", "tentativas", "erro"])


def _leitura(request):
    if not request.user.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        raise PermissionDenied


def _contexto_status(empresa):
    estado = fila.estado_de(empresa)
    return {"estado": estado, "config": fila.config_de(empresa),
            "qr": worker.qr_png(estado.qr) if estado.qr and estado.estado == "AGUARDANDO_QR" else ""}


@login_required
def home(request):
    _leitura(request)
    empresa = request.empresa
    agora = timezone.now()
    inicio_dia = timezone.localtime(agora).replace(hour=0, minute=0, second=0, microsecond=0)
    config = fila.config_de(empresa)
    base = M.objects.filter(empresa=empresa)
    clientes = base.filter(direcao="SAIDA", para_admin=False, status__in=[M.Status.ENVIADA, M.Status.SIMULADA])
    return render(request, "mensageria/home.html", {
        **_contexto_status(empresa),
        "hoje": clientes.filter(enviada_em__gte=inicio_dia).count(),
        "hora": clientes.filter(enviada_em__gte=agora - timedelta(hours=1)).count(),
        "na_fila": base.filter(status=M.Status.PENDENTE).count(), "falhas": base.filter(status=M.Status.FALHA,
                                                                                         criado_em__gte=agora - timedelta(days=7)).count(),
        "lotes": LoteEnvio.objects.filter(empresa=empresa, status=LoteEnvio.Status.AGUARDANDO).prefetch_related("mensagens"),
        "confirmacoes": Confirmacao.objects.filter(empresa=empresa, status="PENDENTE", acao="faturamento.transmitir"),
        "recentes": base.select_related("contato", "anexo").order_by("-criado_em")[:14],
        "na_janela": fila.na_janela(config, agora), "proxima_janela": fila.proxima_janela(config, agora),
        "contatos_aptos": ContatoWhatsApp.objects.filter(empresa=empresa, ativo=True, consentimento=True,
                                                         descadastrado_em__isnull=True).count(),
        "pode_escrever": pode_escrever(request.user, PAPEIS)})


@login_required
def status(request):
    _leitura(request)
    return render(request, "mensageria/_status.html", _contexto_status(request.empresa))


@login_required
def configuracao(request):
    _leitura(request)
    config = fila.config_de(request.empresa)
    form = ConfiguracaoWhatsAppForm(request.POST or None, instance=config)
    if request.method == "POST":
        exigir_escrita(request.user, ["Administrador"])
        if form.is_valid():
            obj = form.save(commit=False)
            chave = form.cleaned_data.get("nova_chave_gemini", "").strip()
            if chave:
                from apps.core.models import Segredo

                obj.gemini_chave = Segredo.criar("Gemini · assistente WhatsApp", chave, "IA", request.empresa)
            if "transporte" in form.changed_data or "ativo" in form.changed_data:
                obj.reiniciar_sessao = True
            obj.save()
            messages.success(request, "Configuração do WhatsApp salva. O worker aplica as mudanças em alguns segundos.")
            return redirect("whatsapp:configuracao")
    return render(request, "mensageria/configuracao.html", {
        "form": form, "pode_salvar": request.user.tem_papel("Administrador") and not request.user.somente_leitura})


@login_required
@require_POST
def teste(request):
    exigir_escrita(request.user, PAPEIS)
    criadas = fila.para_admins(request.empresa, f"✅ Teste do KS CENTRAL às {timezone.localtime():%H:%M}. "
                                                "Envie *ajuda* para ver os comandos disponíveis.")
    if criadas:
        messages.success(request, f"Mensagem de teste na fila para {len(criadas)} número(s). O worker envia em segundos.")
    else:
        messages.error(request, "Cadastre ao menos um número de administrador na configuração.")
    return redirect("whatsapp:home")


@login_required
@require_POST
def reconectar(request):
    exigir_escrita(request.user, PAPEIS)
    from .models import ConfiguracaoWhatsApp

    ConfiguracaoWhatsApp.objects.filter(empresa=request.empresa).update(reiniciar_sessao=True)
    messages.success(request, "Pedido enviado: um novo QR Code aparece aqui em alguns segundos.")
    return redirect("whatsapp:home")


@login_required
@require_POST
def rotinas(request):
    exigir_escrita(request.user, PAPEIS)
    resultado = worker.periodicas(request.empresa)
    messages.success(request, f"Rotinas executadas: {resultado or 'WhatsApp inativo'}.")
    return redirect("whatsapp:home")


@login_required
@require_POST
def lote_acao(request, pk, acao):
    exigir_escrita(request.user, PAPEIS)
    lote = get_object_or_404(LoteEnvio, pk=pk, empresa=request.empresa)
    if acao == "liberar":
        envios.liberar(lote, str(request.user))
        messages.success(request, "Envio liberado. As mensagens seguem o ritmo seguro configurado.")
    elif acao == "cancelar":
        envios.cancelar(lote, str(request.user))
        messages.success(request, "Envio cancelado. Nada foi enviado ao cliente.")
    destino = request.POST.get("_proximo")
    return redirect(destino if destino and destino.startswith("/") else "whatsapp:home")


@login_required
@require_POST
def reenviar(request, pk):
    exigir_escrita(request.user, PAPEIS)
    msg = get_object_or_404(MensagemWhatsApp, pk=pk, empresa=request.empresa, status=M.Status.FALHA)
    msg.status, msg.tentativas, msg.erro, msg.agendada_para = M.Status.PENDENTE, 0, "", timezone.now()
    msg.save()
    messages.success(request, "Mensagem devolvida à fila.")
    return redirect("whatsapp:mensagem_detalhe", pk=pk)


@login_required
@require_POST
def contato_rapido(request, pessoa_pk):
    """Cadastro de contato a partir da tela de comunicação do cliente."""
    exigir_escrita(request.user, PAPEIS)
    from apps.cadastros.models import Pessoa

    pessoa = get_object_or_404(Pessoa, pk=pessoa_pk, empresa=request.empresa)
    dados = request.POST.copy()
    dados["contato-pessoa"] = str(pessoa.pk)
    dados.setdefault("contato-ativo", "on")
    form = ContatoForm(dados, prefix="contato")
    if form.is_valid():
        obj = form.save(commit=False)
        obj.empresa, obj.pessoa = request.empresa, pessoa
        obj.save()
        messages.success(request, f"Contato {obj.nome} adicionado.")
    else:
        messages.error(request, "Contato não salvo: " + "; ".join(f"{form.fields[c].label if c in form.fields else ''} {' '.join(e)}".strip()
                                                                for c, e in form.errors.items()))
    return redirect("cobranca:perfil", pessoa_pk=pessoa.pk)

