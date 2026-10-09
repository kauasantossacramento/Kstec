from django.urls import reverse

from apps.core.agenda import ItemAtencao, atencao

from .models import Sistema


@atencao
def fora_do_ar(empresa, usuario):
    fora = list(Sistema.objects.filter(empresa=empresa, ativo=True, status=Sistema.Status.FORA))
    return [ItemAtencao(f"{s.nome} fora do ar", reverse("sla:sistema_detalhe", args=[s.pk]), "danger", 1,
                        s.ultimo_erro, "activity") for s in fora]
