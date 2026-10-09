from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.contratos.models import Contrato

from .services.lancamentos import centro_contrato


@receiver(post_save, sender=Contrato)
def criar_centro_contrato(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        centro_contrato(instance)
