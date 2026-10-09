"""Avisos ao(s) número(s) do administrador. Silenciosos quando o WhatsApp não está configurado."""

from django.conf import settings

from apps.core.templatetags.ks import brl

from . import confirmacoes
from .fila import config_de, para_admins


def admin(empresa, texto, anexos=(), chave=""):
    config = config_de(empresa)
    if not config.ativo or not config.admins:
        return []
    return para_admins(empresa, texto, anexos, chave)


def ciclo(ciclo, titulo, texto, confirmar=False):
    config = config_de(ciclo.empresa)
    if not config.ativo or not config.admins or not config.avisos_faturamento:
        return []
    link = f"{settings.SITE_URL}/faturamento/ciclos/{ciclo.pk}/"
    corpo = f"🧾 *{titulo}*\n{texto}"
    if confirmar:
        c = confirmacoes.criar(ciclo.empresa, "faturamento.transmitir", ciclo,
                               f"Transmitir NFS-e {ciclo} de {brl(ciclo.valor)}", horas=72)
        corpo += f"\n\nResponda *SIM {c.codigo}* para transmitir ou *NAO {c.codigo}* para manter aguardando."
    corpo += f"\n{link}"
    return admin(ciclo.empresa, corpo, chave=f"ciclo:{ciclo.pk}:{ciclo.status}")


def sistema(sistema, caiu, detalhe=""):
    config = config_de(sistema.empresa)
    if not config.ativo or not config.alertas_monitoramento:
        return []
    if caiu:
        texto = f"🔴 *{sistema.nome} fora do ar*\n{detalhe}\n{sistema.url}"
    else:
        texto = f"🟢 *{sistema.nome} voltou*\n{detalhe}"
    return admin(sistema.empresa, texto, chave=f"sla:{sistema.pk}:{'queda' if caiu else 'retorno'}:{sistema.falhas_consecutivas}:{sistema.ultima_mudanca:%Y%m%d%H%M}" if sistema.ultima_mudanca else "")
