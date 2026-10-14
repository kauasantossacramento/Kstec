"""Leitura da caixa de envio: respostas, avisos automáticos e devoluções vinculados aos e-mails enviados."""

from datetime import timedelta
from decimal import Decimal
from email.message import EmailMessage

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.fiscal.models import EntregaNota, RespostaEmail
from apps.fiscal.services import caixa_email


class ImapFalso:
    def __init__(self, mensagens):
        self.mensagens = [m.as_bytes() for m in mensagens]

    def login(self, *a):
        return "OK", []

    def select(self, *a, **k):
        return "OK", []

    def search(self, *a):
        return "OK", [" ".join(str(i + 1) for i in range(len(self.mensagens))).encode()]

    def fetch(self, num, _partes):
        return "OK", [(b"", self.mensagens[int(num) - 1])]

    def logout(self):
        return "OK", []


def msg(remetente, assunto, texto, **cab):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = remetente, "financeiro@kstec.online", assunto
    m["Date"] = timezone.now().strftime("%a, %d %b %Y %H:%M:%S -0300")
    m["Message-ID"] = cab.pop("mid")
    for k, v in cab.items():
        m[k.replace("_", "-")] = v
    m.set_content(texto)
    return m


@pytest.fixture
def envio(empresa, contrato):
    from apps.catalogo.models import ItemCatalogo
    from apps.catalogo.seeds import seed
    from apps.core.models import Anexo, ContaEmail, Segredo
    from apps.fiscal.models import NotaFiscal, PerfilFiscal

    seed(empresa)
    nota = NotaFiscal.objects.create(empresa=empresa, tomador=contrato.cliente, contrato=contrato, competencia=timezone.localdate().replace(day=1),
                                     item_catalogo=ItemCatalogo.objects.get(empresa=empresa, codigo_interno="TI-SUP"),
                                     perfil=PerfilFiscal.objects.create(empresa=empresa, nome="P", aliquota_iss=Decimal("2")),
                                     valor_servicos=Decimal("100"), valor_liquido=Decimal("100"), discriminacao="x",
                                     status="AUTORIZADA", numero_nfse="77", ambiente=1)
    e = EntregaNota.objects.create(empresa=empresa, nota=nota, destinatarios=["dti@exemplo.gov.br"],
                                   assunto="Para atesto — NFS-e 77 — Competência 09/2026", mensagem="Segue a nota.",
                                   pacote=Anexo.criar(nota, "p.zip", b"PK"), manifesto={})
    EntregaNota.objects.filter(pk=e.pk).update(status="ENVIADA", enviado_em=timezone.now() - timedelta(hours=2),
                                               message_id="<envio-77@kstec.online>")
    ContaEmail.objects.create(empresa=empresa, finalidade="DOCUMENTOS", email="financeiro@kstec.online",
                              senha=Segredo.criar("SMTP", "x", "INTEGRACAO", empresa))
    return EntregaNota.objects.get(pk=e.pk)


def test_vincula_resposta_aviso_e_devolucao(empresa, envio):
    devolucao = msg("MAILER-DAEMON@mail.exemplo", "Undelivered Mail Returned to Sender", "User unknown", mid="<d1@x>")
    original = EmailMessage()
    original["Subject"], original["Message-ID"] = envio.assunto, "<envio-77@kstec.online>"
    devolucao.add_attachment(original)
    caixa = ImapFalso([
        msg("Setor <dti@exemplo.gov.br>", "Re: " + envio.assunto, "Recebido, vamos atestar.\n\nEm seg, 13 de out, KS TEC escreveu:\n> antigo",
            mid="<r1@x>", In_Reply_To="<envio-77@kstec.online>"),
        msg("dti@exemplo.gov.br", "RE:", "Esta é uma mensagem gerada automaticamente. Acusamos o recebimento.", mid="<a1@x>"),
        devolucao,
        msg("promo@loja.com", "Oferta", "compre já", mid="<p1@x>"),
    ])
    assert caixa_email.sincronizar(empresa, imap=caixa) == 3
    tipos = {r.tipo: r for r in RespostaEmail.objects.filter(entrega=envio)}
    assert set(tipos) == {"RESPOSTA", "AUTOMATICA", "DEVOLUCAO"}
    assert tipos["RESPOSTA"].vinculo == "cabeçalho" and tipos["RESPOSTA"].texto == "Recebido, vamos atestar."
    assert tipos["DEVOLUCAO"].vinculo == "cabeçalho" and tipos["AUTOMATICA"].vinculo == "remetente"
    assert caixa_email.sincronizar(empresa, imap=caixa) == 0          # não duplica


def test_tela_de_emails_enviados(cli, empresa, envio, monkeypatch):
    RespostaEmail.objects.create(empresa=empresa, entrega=envio, message_id="<r9@x>", remetente="dti@exemplo.gov.br",
                                 assunto="Re: atesto", recebido_em=timezone.now(), texto="Atestado e encaminhado.")
    pagina = cli.get(reverse("fiscal:emails")).content.decode()
    assert envio.assunto in pagina and "Atestado e encaminhado." in pagina and "Respondido" in pagina
    assert "NFS-e 77" in cli.get(reverse("fiscal:emails") + "?filtro=respondidos").content.decode()
    monkeypatch.setattr(caixa_email, "sincronizar", lambda empresa: 2)
    assert cli.post(reverse("fiscal:emails")).status_code == 302


def test_envio_grava_message_id(empresa, envio, settings, monkeypatch):
    from apps.fiscal.services import entregas

    settings.EMAIL_CONTAS_SMTP = False
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    EntregaNota.objects.filter(pk=envio.pk).update(status="PREPARADA", message_id="")
    monkeypatch.setattr(entregas, "revalidar_entrega", lambda e: None)
    from apps.core.models import Anexo

    Anexo.objects.filter(pk=envio.pacote_id).update(hash_sha256=__import__("hashlib").sha256(b"PK").hexdigest())
    monkeypatch.setattr(entregas, "anexos_email", lambda dados: [])
    feito = entregas.enviar_entrega(EntregaNota.objects.get(pk=envio.pk))
    assert feito.message_id.startswith("<") and feito.message_id.endswith(">")
