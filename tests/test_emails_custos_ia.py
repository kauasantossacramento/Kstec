"""E-mails configuráveis, alertas por e-mail, custos com rateio, central de documentos, SLA, cliente sem CNPJ e IA."""

from datetime import date, timedelta
from decimal import Decimal

import httpx
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.cadastros.models import Pessoa
from apps.contratos.models import DocumentoContrato
from apps.core.models import Anexo, ContaEmail, Segredo
from apps.core.services.email import enviar, lista_emails
from apps.financeiro.models import CategoriaFinanceira, CentroCusto, Lancamento
from apps.financeiro.services.custos_relatorio import apurar, xlsx
from apps.financeiro.services.lancamentos import centro_contrato
from apps.mensageria.models import Confirmacao
from apps.mensageria.services import assistente, comandos, confirmacoes, fila
from apps.sla.models import Sistema
from apps.sla.services import alertas_email, monitor
from apps.sla.services import relatorio as sla_relatorio


def test_lista_emails_e_envio_pela_conta(empresa):
    assert lista_emails("A@x.com; b@y.com, a@x.com", ["c@z.com"]) == ["a@x.com", "b@y.com", "c@z.com"]
    ContaEmail.objects.create(empresa=empresa, finalidade="ALERTAS", email="gestao@kstec.online",
                              senha=Segredo.criar("smtp", "segredo", empresa=empresa))
    assert enviar("ALERTAS", "Assunto", "Corpo", "dest@cliente.gov.br") == 1
    assert mail.outbox[-1].to == ["dest@cliente.gov.br"]  # perfil de teste nunca usa SMTP real


def test_pessoa_sem_documento_e_emails_de_envio(empresa):
    a = Pessoa.objects.create(empresa=empresa, cpf_cnpj="", razao_social="INVICTA (CNPJ em registro)",
                              email_nf="nf@invicta.com", emails_documentos="fin@invicta.com; nf@invicta.com")
    Pessoa.objects.create(empresa=empresa, cpf_cnpj="", razao_social="Outro sem documento")
    assert a.emails_envio == ["nf@invicta.com", "fin@invicta.com"]


def test_custos_rateio_global_proporcional(empresa, contrato):
    rec = CategoriaFinanceira.objects.create(empresa=empresa, nome="Rec", tipo="RECEITA", grupo_dre="RECEITA_BRUTA")
    desp = CategoriaFinanceira.objects.create(empresa=empresa, nome="Infra", tipo="DESPESA", grupo_dre="CUSTO_SERVICO")
    centro = centro_contrato(contrato)
    glob = CentroCusto.objects.create(empresa=empresa, nome="Administrativo", ratear=True)
    hoje = timezone.localdate()

    def lanc(tipo, cat, c, valor):
        Lancamento.objects.create(empresa=empresa, tipo=tipo, descricao="x", categoria=cat, centro_custo=c,
                                  valor=Decimal(valor), data_competencia=hoje, data_vencimento=hoje)
    lanc("RECEITA", rec, centro, "5000")
    lanc("DESPESA", desp, centro, "1000")
    lanc("DESPESA", desp, glob, "600")
    dados = apurar(empresa, hoje.replace(day=1), hoje)
    linha = dados["linhas"][0]
    assert (linha["direto"], linha["rateio"], linha["resultado"]) == (Decimal("1000"), Decimal("600.00"), Decimal("3400.00"))
    assert xlsx(dados)[:2] == b"PK"


def test_alertas_email_por_sistema_e_gerais(empresa, contrato, django_capture_on_commit_callbacks):
    config = alertas_email.configuracao(empresa)
    config.emails_gerais = "kaua@kstec.online"
    config.save()
    s = Sistema.objects.create(empresa=empresa, nome="Portal", url="https://portal.example", contrato=contrato,
                               emails_alerta="ti@cliente.gov.br", falhas_para_alerta=1, alertar_whatsapp=False)
    assert alertas_email.destinatarios(config, s) == ["ti@cliente.gov.br", "kaua@kstec.online"]
    with django_capture_on_commit_callbacks(execute=True):
        monitor.verificar(s, httpx.MockTransport(lambda r: httpx.Response(503)))
    enviado = mail.outbox[-1]
    assert "Portal" in enviado.subject and "fora do ar" in enviado.subject and "HTTP 503" in enviado.body
    assert set(enviado.to) == {"ti@cliente.gov.br", "kaua@kstec.online"}
    assunto, corpo = alertas_email.renderizar(config, {"sistema": "X"}, "retorno")
    assert "X" in assunto and "{" not in corpo


def test_relatorio_sla_e_central_de_documentos(cli, empresa, contrato):
    s = Sistema.objects.create(empresa=empresa, nome="Portal", url="https://portal.example", contrato=contrato)
    monitor.verificar(s, httpx.MockTransport(lambda r: httpx.Response(200)))
    rel = sla_relatorio.novo(contrato, timezone.localdate())
    assert rel.dados["sistemas"][0]["uptime"] == 100.0
    anexo = Anexo.criar(contrato, "relatorio_assinado.pdf", b"%PDF-1.4 teste")
    DocumentoContrato.objects.create(empresa=empresa, contrato=contrato, tipo="RELATORIO_ATIVIDADES",
                                     competencia=date(2026, 6, 15), titulo="Relatório junho assinado", anexo=anexo)
    resposta = cli.get(reverse("relatorios:home") + f"?contrato={contrato.pk}")
    assert resposta.status_code == 200 and "Relatório junho assinado" in resposta.content.decode()
    assert "Relatório de SLA" in resposta.content.decode()
    assert cli.get(reverse("relatorios:sla", args=[rel.pk])).status_code == 200
    assert cli.get(reverse("core:anexo_baixar", args=[anexo.pk]) + "?ver=1").status_code == 200
    for url in (reverse("custos:planilha_lista"), reverse("custos:exportar"), reverse("sla:alertas"), reverse("core:emails")):
        assert cli.get(url).status_code == 200, url


def test_tela_contas_email_salva_senha_cifrada(cli, empresa):
    dados = {"finalidade": "DOCUMENTOS", "documentos-ativo": "on", "documentos-nome_remetente": "KS TEC Financeiro",
             "documentos-email": "financeiro@kstec.online", "documentos-host": "smtp.hostinger.com",
             "documentos-porta": "465", "documentos-seguranca": "SSL", "documentos-nova_senha": "senha-app"}
    assert cli.post(reverse("core:emails"), dados).status_code == 302
    conta = ContaEmail.objects.get(finalidade="DOCUMENTOS")
    assert conta.senha.ler() == "senha-app" and b"senha-app" not in bytes(conta.senha.valor_criptografado)


class GeminiFalso:
    """Simula o cliente: chama a ferramenta pedida e devolve o texto dela."""

    def __init__(self, ferramenta, **args):
        self.ferramenta, self.args = ferramenta, args
        self.models = self

    def generate_content(self, model, contents, config):
        funcoes = {f.__name__: f for f in config.tools}
        texto = funcoes[self.ferramenta](**self.args)
        return type("R", (), {"text": texto})()


def _config_ia(empresa):
    c = fila.config_de(empresa)
    c.ativo, c.assistente_ia, c.numeros_admin = True, True, "5575999990000"
    c.gemini_chave = Segredo.criar("gemini", "chave", "IA", empresa)
    c.save()


def test_assistente_registra_despesa_so_apos_confirmacao(empresa):
    _config_ia(empresa)
    CategoriaFinanceira.objects.create(empresa=empresa, nome="Administrativas", tipo="DESPESA", grupo_dre="DESPESA_OPERACIONAL")
    CentroCusto.objects.create(empresa=empresa, nome="Administrativo")
    falso = GeminiFalso("registrar_despesa", descricao="Hospedagem", valor=199.9,
                        vencimento=(date.today() + timedelta(days=5)).strftime("%d/%m/%Y"))
    textos, _ = assistente.responder(empresa, "5575999990000", "lança 199,90 de hospedagem", cliente=falso)
    assert "SIM" in textos[0] and not Lancamento.objects.exists()
    pedido = Confirmacao.objects.get(acao="financeiro.despesa")
    confirmacoes.responder(empresa, pedido.codigo, True)
    lanc = Lancamento.objects.get()
    assert lanc.valor == Decimal("199.90") and lanc.tipo == "DESPESA" and lanc.centro_custo.nome == "Administrativo"


def test_assistente_consulta_e_volta_aos_comandos_sem_chave(empresa):
    _config_ia(empresa)
    textos, _ = assistente.responder(empresa, "5575999990000", "como estão os sistemas?",
                                     cliente=GeminiFalso("status_monitoramento"))
    assert "Nenhum sistema" in textos[0]
    c = fila.config_de(empresa)
    c.assistente_ia = False
    c.save()
    assert assistente.responder(empresa, "5575999990000", "oi") is None
    assert comandos.responder_admin(empresa, "status", "5575999990000", "status")[0]
