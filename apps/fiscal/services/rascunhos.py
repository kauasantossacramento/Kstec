"""Validação de origem, segregação por empresa e persistência auditada."""

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import NotaFiscal
from .calculo import calcular


def preparar(nota):
    for campo in ("tomador", "item_catalogo", "perfil", "contrato"):
        objeto = getattr(nota, campo, None)
        if objeto is not None and objeto.empresa_id != nota.empresa_id:
            raise ValidationError("Todos os vínculos devem pertencer à mesma empresa.")
    if nota.contrato_id and nota.contrato.cliente_id != nota.tomador_id:
        raise ValidationError("O tomador deve ser o cliente do contrato.")
    if not nota.item_catalogo.ativo or not nota.perfil.ativo:
        raise ValidationError("Selecione um item e um perfil ativos.")
    if nota.item_catalogo.pendencias_fiscais:
        raise ValidationError(nota.item_catalogo.pendencias_fiscais)
    return calcular(nota, nota.perfil)


@transaction.atomic
def salvar(nota):
    if not nota._state.adding:
        atual = NotaFiscal.objects.select_for_update().get(pk=nota.pk, empresa=nota.empresa)
        if atual.status != NotaFiscal.Status.RASCUNHO:
            raise ValidationError("Somente rascunhos podem ser editados.")
    if nota.status != NotaFiscal.Status.RASCUNHO:
        raise ValidationError("A preparação local salva apenas rascunhos.")
    preparar(nota)
    nota.tomador_snapshot = nota.tomador.snapshot()
    item = nota.item_catalogo
    nota.servico_snapshot = {"codigo_interno": item.codigo_interno, "descricao": str(item),
                            "valor_servicos": str(nota.valor_servicos), "discriminacao": nota.discriminacao,
                            "item_lc116": str(item.item_lc116_id or ""),
                            "codigo_tributacao_nacional": str(item.codigo_tributacao_nacional_id or ""),
                            "codigo_tributacao_municipal": item.codigo_tributacao_municipal,
                            "nbs": str(item.nbs_id or "")}
    nota.perfil_snapshot = {campo.name: str(getattr(nota.perfil, campo.name))
                           for campo in nota.perfil._meta.fields
                           if campo.name.startswith(("aliquota_", "reter_")) or campo.name in ("nome", "iss_retido", "observacao_legal")}
    nota.full_clean()
    nota.save()
    return nota
