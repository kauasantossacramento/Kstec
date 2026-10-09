from celery import shared_task

from .services.notificacoes import notificar_papeis


@shared_task
def lembrete_teste_restauracao():
    """Lembrete mensal do teste de restauração de backup (seção 12)."""
    notificar_papeis(
        ["Administrador"],
        "Teste mensal de restauração de backup",
        "Execute ./scripts/restore.sh <arquivo> --teste na VPS e registre o tempo (manual de deploy, seção 8).",
        nivel="warning", email=True, chave_dedup="backup-restauracao",
    )
