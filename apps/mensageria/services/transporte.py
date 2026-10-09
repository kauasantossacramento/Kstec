"""Transportes do WhatsApp. O worker usa um único transporte; views e tarefas apenas enfileiram."""

import logging
import mimetypes
import threading
import time

log = logging.getLogger(__name__)


class ErroTransporte(Exception):
    pass


class TransporteSimulado:
    """Não envia nada: registra no log e marca a mensagem como SIMULADA. Padrão local e nos testes."""

    nome = "SIMULADO"
    simulado = True

    def __init__(self, ao_receber=None, ao_estado=None):
        self.ao_receber = ao_receber
        self.ao_estado = ao_estado
        self.enviados = []

    def iniciar(self):
        if self.ao_estado:
            self.ao_estado("CONECTADO", conta="simulado")

    def parar(self):
        pass

    def pronto(self):
        return True

    def verificar(self, telefone):
        return True, f"{telefone}@s.whatsapp.net"

    def digitando(self, destino, segundos):
        pass

    def enviar_texto(self, destino, texto):
        self.enviados.append(("texto", destino, texto))
        log.info("whatsapp simulado: texto para %s (%d caracteres)", destino[-4:], len(texto))
        return f"SIM-{len(self.enviados)}"

    def enviar_documento(self, destino, conteudo, nome, legenda=""):
        self.enviados.append(("documento", destino, nome))
        log.info("whatsapp simulado: documento %s para %s", nome, destino[-4:])
        return f"SIM-{len(self.enviados)}"


class TransporteNeonize:
    """WhatsApp Web via neonize (whatsmeow). A sessão fica em arquivo SQLite fora do Git."""

    nome = "NEONIZE"
    simulado = False

    def __init__(self, caminho_sessao, ao_receber=None, ao_estado=None):
        from neonize.client import NewClient
        from neonize.events import ConnectedEv, DisconnectedEv, LoggedOutEv, MessageEv, PairStatusEv

        self.ao_receber = ao_receber
        self.ao_estado = ao_estado
        self.client = NewClient(str(caminho_sessao))
        self._thread = None
        self._jids = {}

        @self.client.qr
        def _qr(_cliente, dados: bytes):
            if self.ao_estado:
                self.ao_estado("AGUARDANDO_QR", qr=dados.decode() if isinstance(dados, bytes) else str(dados))

        @self.client.event(ConnectedEv)
        def _conectado(cliente, _ev):
            conta = ""
            try:
                conta = cliente.get_me().JID.User
            except Exception:  # noqa: BLE001
                pass
            if self.ao_estado:
                self.ao_estado("CONECTADO", conta=conta)

        @self.client.event(PairStatusEv)
        def _pareado(_cliente, ev):
            if self.ao_estado:
                self.ao_estado("CONECTADO", conta=getattr(getattr(ev, "ID", None), "User", ""))

        @self.client.event(LoggedOutEv)
        def _saiu(_cliente, _ev):
            if self.ao_estado:
                self.ao_estado("DESCONECTADO", detalhe="Sessão encerrada no celular. Leia o QR novamente.")

        @self.client.event(DisconnectedEv)
        def _caiu(_cliente, _ev):
            if self.ao_estado:
                self.ao_estado("DESCONECTADO", detalhe="Conexão perdida; reconectando.")

        @self.client.event(MessageEv)
        def _mensagem(_cliente, ev):
            try:
                self._receber(ev)
            except Exception:  # noqa: BLE001 — nunca derrubar o laço de eventos.
                log.exception("falha ao processar mensagem recebida")

    # ---- eventos ----
    def _receber(self, ev):
        from neonize.utils.message import extract_text

        fonte = ev.Info.MessageSource
        if fonte.IsFromMe or fonte.IsGroup or not self.ao_receber:
            return
        jid = fonte.Sender
        alternativo = getattr(fonte, "SenderAlt", None)
        if getattr(jid, "Server", "") != "s.whatsapp.net" and alternativo is not None and alternativo.User:
            jid = alternativo
        if getattr(jid, "Server", "") != "s.whatsapp.net":
            return
        texto = extract_text(ev.Message) or ""
        if texto.strip():
            self.ao_receber(jid.User, texto, ev.Info.ID)

    # ---- ciclo de vida ----
    def iniciar(self):
        self._thread = threading.Thread(target=self.client.connect, name="neonize", daemon=True)
        self._thread.start()

    def parar(self):
        try:
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def pronto(self):
        try:
            return bool(self.client.is_connected and self.client.is_logged_in)
        except Exception:  # noqa: BLE001
            return False

    # ---- envio ----
    def _jid(self, destino):
        from neonize.utils import build_jid

        usuario, _, servidor = destino.partition("@")
        return build_jid(usuario, servidor or "s.whatsapp.net")

    def verificar(self, telefone):
        if telefone in self._jids:
            return True, self._jids[telefone]
        try:
            resposta = self.client.is_on_whatsapp(telefone)
        except Exception as erro:  # noqa: BLE001
            raise ErroTransporte(f"verificação indisponível: {erro}") from None
        if not resposta or not resposta[0].IsIn:
            return False, ""
        jid = f"{resposta[0].JID.User}@{resposta[0].JID.Server}"
        self._jids[telefone] = jid
        return True, jid

    def digitando(self, destino, segundos):
        from neonize.utils.enum import ChatPresence, ChatPresenceMedia

        jid = self._jid(destino)
        try:
            self.client.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_COMPOSING, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
            time.sleep(segundos)
            self.client.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_PAUSED, ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
        except Exception:  # noqa: BLE001 — presença é cosmética.
            time.sleep(segundos)

    def enviar_texto(self, destino, texto):
        try:
            return self.client.send_message(self._jid(destino), texto).ID
        except Exception as erro:  # noqa: BLE001
            raise ErroTransporte(str(erro)[:250]) from None

    def enviar_documento(self, destino, conteudo, nome, legenda=""):
        tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        try:
            return self.client.send_document(self._jid(destino), conteudo, caption=legenda or None, title=nome,
                                             filename=nome, mimetype=tipo).ID
        except Exception as erro:  # noqa: BLE001
            raise ErroTransporte(str(erro)[:250]) from None
