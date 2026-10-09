"""Processo do WhatsApp: mantém a sessão, consome a fila no ritmo seguro e recebe comandos.

Uso:
    python manage.py whatsapp_worker            # transporte da configuração (neonize ou simulado)
    python manage.py whatsapp_worker --simulado # força o simulado (não envia nada)

Rode apenas UMA instância por número. Em produção é o serviço `whatsapp` do docker compose.
"""

import signal
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from apps.core import contexto
from apps.core.models import Empresa
from apps.core.travas import TravaOcupada, trava
from apps.mensageria.models import ConfiguracaoWhatsApp, EstadoSessao
from apps.mensageria.services import fila, worker
from apps.mensageria.services.transporte import TransporteNeonize, TransporteSimulado


class Command(BaseCommand):
    help = "Executa o worker do WhatsApp (sessão neonize, fila de envio e comandos)."

    def add_arguments(self, parser):
        parser.add_argument("--simulado", action="store_true", help="Não conecta ao WhatsApp; apenas simula envios.")
        parser.add_argument("--cnpj", default="", help="Empresa (padrão: a primeira cadastrada).")
        parser.add_argument("--uma-vez", action="store_true", help="Processa a fila disponível e encerra (diagnóstico).")

    def handle(self, *args, **opts):
        empresa = Empresa.objects.filter(cnpj=opts["cnpj"]).first() if opts["cnpj"] else Empresa.objects.order_by("criado_em").first()
        if empresa is None:
            raise CommandError("Nenhuma empresa cadastrada.")
        self.parar = False
        signal.signal(signal.SIGINT, self._sinal)
        signal.signal(signal.SIGTERM, self._sinal)
        try:
            with trava(f"whatsapp:worker:{empresa.pk}", ttl=120):
                self._executar(empresa, opts)
        except TravaOcupada:
            raise CommandError("Já existe um worker do WhatsApp ativo para esta empresa.") from None

    def _sinal(self, *_):
        self.parar = True

    def _executar(self, empresa, opts):
        """Laço externo: (re)cria o transporte quando a configuração muda, quando a tela pede novo QR
        ou quando o QR expira sem pareamento — sem precisar reiniciar o contêiner."""
        with contexto.usar_contexto(empresa):
            while not self.parar:
                motivo = self._sessao(empresa, opts)
                if motivo is None or opts["uma_vez"]:
                    break
                self.stdout.write(f"[whatsapp] recriando conexão: {motivo}")
                self._dormir(3)

    def _transporte(self, empresa, opts):
        config = fila.config_de(empresa)

        def ao_estado(estado, **kw):
            worker.atualizar_estado(empresa, estado, **kw)
            self.stdout.write(f"[whatsapp] {estado} {kw.get('conta', '') or kw.get('detalhe', '')}")

        def ao_receber(telefone, texto, wa_id):
            worker.receber(empresa, telefone, texto, wa_id)

        if config.transporte == ConfiguracaoWhatsApp.Transporte.NEONIZE and not opts["simulado"]:
            caminho = Path(settings.WHATSAPP_SESSAO)
            caminho.parent.mkdir(parents=True, exist_ok=True)
            return TransporteNeonize(caminho, ao_receber=ao_receber, ao_estado=ao_estado)
        return TransporteSimulado(ao_receber=ao_receber, ao_estado=ao_estado)

    def _motivo_recriar(self, empresa, transporte):
        config = ConfiguracaoWhatsApp.objects.filter(empresa=empresa).first()
        if config is None:
            return None
        if config.reiniciar_sessao:
            ConfiguracaoWhatsApp.objects.filter(pk=config.pk).update(reiniciar_sessao=False)
            return "pedido pela tela"
        if transporte.nome != config.transporte:
            return f"transporte alterado para {config.transporte}"
        estado = EstadoSessao.objects.filter(empresa=empresa).first()
        if (transporte.nome == "NEONIZE" and estado and estado.estado == EstadoSessao.Estado.AGUARDANDO_QR
                and estado.qr_em and timezone.now() - estado.qr_em > timedelta(minutes=3) and not transporte.pronto()):
            return "QR Code expirou sem pareamento"
        return None

    def _sessao(self, empresa, opts):
        transporte = self._transporte(empresa, opts)
        self.stdout.write(self.style.SUCCESS(f"Worker do WhatsApp iniciado ({transporte.nome}) para {empresa}."))
        transporte.iniciar()
        proxima_rotina = timezone.now()
        renovar_trava = verificar_config = time.monotonic()
        motivo = None
        try:
            while not self.parar:
                close_old_connections()
                agora = timezone.now()
                worker.batimento(empresa)
                if agora >= proxima_rotina:
                    try:
                        worker.periodicas(empresa, agora)
                    except Exception as erro:  # noqa: BLE001 — rotinas não derrubam o envio.
                        self.stderr.write(f"[whatsapp] rotina falhou: {erro}")
                    proxima_rotina = agora + timedelta(minutes=5)
                if time.monotonic() - renovar_trava > 60:
                    from django.core.cache import cache

                    cache.touch(f"trava:whatsapp:worker:{empresa.pk}", 120)
                    renovar_trava = time.monotonic()
                if time.monotonic() - verificar_config > 5:
                    verificar_config = time.monotonic()
                    motivo = self._motivo_recriar(empresa, transporte)
                    if motivo:
                        break
                espera = worker.passo(empresa, transporte, agora)
                if opts["uma_vez"] and espera >= 3:
                    break
                self._dormir(min(espera, 5))
        finally:
            transporte.parar()
            EstadoSessao.objects.filter(empresa=empresa).update(
                estado=EstadoSessao.Estado.DESLIGADO if not motivo else EstadoSessao.Estado.DESCONECTADO,
                qr="", detalhe="Worker encerrado." if not motivo else f"Reconectando: {motivo}.")
            if not motivo:
                self.stdout.write("Worker do WhatsApp encerrado.")
        return motivo

    def _dormir(self, segundos):
        fim = time.monotonic() + max(0.2, float(segundos))
        while not self.parar and (restante := fim - time.monotonic()) > 0:
            time.sleep(min(0.5, restante))
