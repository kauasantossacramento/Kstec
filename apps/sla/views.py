from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.crud import Coluna, Crud, DetalheGenerico
from apps.core.forms import FormKS
from apps.core.permissoes import exigir_escrita, pode_escrever

from .models import ConfiguracaoAlertas, Incidente, Sistema
from .services import monitor

PAPEIS = ["Operação", "Fiscal", "Financeiro"]

sistemas = Crud(Sistema, "sistema", "sla", [
    Coluna("Sistema", "nome", link=True), Coluna("Endereço", "url"), Coluna("Contrato", "contrato"),
    Coluna("Situação", "status", "status", "Sistema")], caminho="sistemas",
    fields=["nome", "url", "contrato", "metodo", "status_esperado", "palavra_chave", "intervalo_min", "timeout_s",
            "lento_ms", "falhas_para_alerta", "meta_sla", "alertar_whatsapp", "alertar_email", "emails_alerta",
            "incluir_gerais", "em_manutencao", "ativo"],
    papeis_escrita=PAPEIS, busca=["nome", "url"], filtros=["status"], select_related=["contrato"],
    titulo="Sistema monitorado", titulo_plural="Sistemas monitorados", template_detalhe="sla/sistema_detalhe.html",
    campos_detalhe=["url", "contrato", "metodo", "status_esperado", "palavra_chave", "intervalo_min", "timeout_s",
                    "lento_ms", "falhas_para_alerta", "alertar_whatsapp", "em_manutencao", "ssl_expira_em"])


class DetalheSistema(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        s = self.object
        def pct(v):
            return f"{v:.2f}%".replace(".", ",") if v is not None else "—"
        medio = s.tempo_medio(24)
        ctx.update({"barras": monitor.uptime_diario(s, 60), "incidentes": s.incidentes.all()[:15],
                    "verificacoes": s.verificacoes.all()[:20], "uptime30": pct(s.uptime(30)),
                    "uptime7": pct(s.uptime(7)), "medio": f"{medio} ms" if medio else "—",
                    "ssl": f"{timezone.localtime(s.ssl_expira_em):%d/%m/%Y}" if s.ssl_expira_em else "—"})
        return ctx


@login_required
def home(request):
    lista = list(Sistema.objects.filter(empresa=request.empresa, ativo=True).select_related("contrato"))
    for s in lista:
        s.barras = monitor.uptime_diario(s, 30)
    return render(request, "sla/home.html", {
        "sistemas": lista, "fora": sum(1 for s in lista if s.status == "FORA"),
        "incidentes": Incidente.objects.filter(empresa=request.empresa).select_related("sistema")[:8],
        "pode_escrever": pode_escrever(request.user, PAPEIS)})


@login_required
@require_POST
def verificar_agora(request, pk):
    exigir_escrita(request.user, PAPEIS)
    s = get_object_or_404(Sistema, pk=pk, empresa=request.empresa)
    s = monitor.verificar(s)
    messages.success(request, f"{s.nome}: {s.get_status_display()}" + (f" · {s.ultimo_tempo_ms} ms" if s.ultimo_tempo_ms else ""))
    destino = request.POST.get("_proximo")
    return redirect(destino if destino and destino.startswith("/") else "sla:home")


@login_required
@require_POST
def verificar_todos(request):
    exigir_escrita(request.user, PAPEIS)
    total = sum(1 for s in Sistema.objects.filter(empresa=request.empresa, ativo=True) if monitor.verificar(s))
    messages.success(request, f"{total} sistema(s) verificado(s).")
    return redirect("sla:home")


class AlertasForm(FormKS):
    class Meta:
        model = ConfiguracaoAlertas
        fields = ["enviar_email", "emails_gerais", "assunto_queda", "corpo_queda", "assunto_retorno", "corpo_retorno"]

    def clean_emails_gerais(self):
        from django.core.validators import validate_email

        from apps.core.services.email import lista_emails

        emails = lista_emails(self.cleaned_data.get("emails_gerais") or "")
        for e in emails:
            validate_email(e)
        return "; ".join(emails)


@login_required
def alertas(request):
    from .services import alertas_email as srv

    config = srv.configuracao(request.empresa)
    form = AlertasForm(request.POST or None, instance=config)
    if request.method == "POST":
        exigir_escrita(request.user, PAPEIS)
        if form.is_valid():
            form.save()
            messages.success(request, "Alertas salvos.")
            return redirect("sla:alertas")
    ctx = srv.exemplo(request.empresa)
    previas = {ev: srv.renderizar(config, ctx, ev) for ev in ("queda", "retorno")}
    sistemas = Sistema.objects.filter(empresa=request.empresa, ativo=True)
    return render(request, "sla/alertas.html", {"form": form, "previas": previas, "placeholders": config.PLACEHOLDERS,
                  "sistemas": [(s, srv.destinatarios(config, s)) for s in sistemas],
                  "pode_escrever": pode_escrever(request.user, PAPEIS)})


@login_required
@require_POST
def alertas_previa(request):
    """Prévia (HTMX) com o texto ainda não salvo."""
    from .models import ConfiguracaoAlertas
    from .services import alertas_email as srv

    config = ConfiguracaoAlertas(**{c: request.POST.get(c, "") for c in
                                    ("assunto_queda", "corpo_queda", "assunto_retorno", "corpo_retorno")})
    try:
        previas = {ev: srv.renderizar(config, srv.exemplo(request.empresa), ev) for ev in ("queda", "retorno")}
    except (ValueError, IndexError) as erro:
        previas = {"erro": str(erro)}
    return render(request, "sla/_previa_alertas.html", {"previas": previas})
