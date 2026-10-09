"""Regras de alocação, ciclo da tarefa e apontamento com auditoria."""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.core.models import Usuario
from apps.core.permissoes import exigir_escrita

from .models import Apontamento, Tarefa


def visiveis(usuario, empresa):
    qs = Tarefa.objects.filter(empresa=empresa)
    if not usuario.tem_papel("Administrador", "Financeiro", "Fiscal", "Leitura"):
        alocados = Contrato.objects.filter(empresa=empresa, responsaveis=usuario).values("pk")
        qs = qs.filter(Q(contrato_id__in=alocados) | Q(contrato__isnull=True, responsavel=usuario))
    return qs


def validar(tarefa, usuario):
    exigir_escrita(usuario, ["Operação"])
    if tarefa.empresa_id != usuario.empresa_id:
        raise PermissionDenied
    for campo in ("contrato", "responsavel", "solicitante"):
        objeto = getattr(tarefa, campo, None)
        if objeto and objeto.empresa_id != tarefa.empresa_id:
            raise ValidationError("Todos os vínculos devem pertencer à mesma empresa.")
    if not tarefa.responsavel.is_active:
        raise ValidationError("Selecione um responsável ativo.")
    if tarefa.contrato_id:
        if tarefa.solicitante_id and tarefa.solicitante.pessoa_id != tarefa.contrato.cliente_id:
            raise ValidationError("O solicitante deve ser um contato do cliente do contrato.")
        if not tarefa.responsavel.tem_papel("Administrador") and not tarefa.contrato.responsaveis.filter(pk=tarefa.responsavel_id).exists():
            raise ValidationError("O responsável deve estar alocado ao contrato.")
    if not usuario.tem_papel("Administrador"):
        if tarefa.contrato_id and not tarefa.contrato.responsaveis.filter(pk=usuario.pk).exists():
            raise PermissionDenied
        if not tarefa.contrato_id and tarefa.responsavel_id != usuario.pk:
            raise PermissionDenied
    if tarefa.data_abertura > timezone.localdate():
        raise ValidationError("A abertura não pode ter data futura.")
    if tarefa.prazo and tarefa.prazo < tarefa.data_abertura:
        raise ValidationError("O prazo não pode ser anterior à abertura.")


@transaction.atomic
def salvar(tarefa, usuario):
    if not tarefa._state.adding:
        atual = visiveis(usuario, tarefa.empresa).select_for_update().filter(pk=tarefa.pk).first()
        if atual is None:
            raise PermissionDenied
        if atual.status in ("CONCLUIDA", "CANCELADA"):
            raise ValidationError("Reabra a tarefa antes de editar.")
        tarefa.status, tarefa.concluida_em = atual.status, atual.concluida_em
    validar(tarefa, usuario)
    tarefa.full_clean()
    tarefa.save()
    return tarefa


TRANSICOES = {
    "A_FAZER": ["EM_ANDAMENTO", "CANCELADA"],
    "EM_ANDAMENTO": ["A_FAZER", "EM_REVISAO", "CONCLUIDA", "CANCELADA"],
    "EM_REVISAO": ["EM_ANDAMENTO", "CONCLUIDA", "CANCELADA"],
    "CONCLUIDA": ["EM_ANDAMENTO"], "CANCELADA": ["A_FAZER"],
}


@transaction.atomic
def transicionar(tarefa, status, usuario):
    obj = visiveis(usuario, tarefa.empresa).select_for_update().filter(pk=tarefa.pk).first()
    if obj is None:
        raise PermissionDenied
    validar(obj, usuario)
    if status not in TRANSICOES[obj.status]:
        raise ValidationError("Mudança de situação inválida.")
    if status == "CONCLUIDA" and obj.entrar_no_relatorio and not obj.resumo_para_relatorio.strip():
        raise ValidationError("Preencha o resumo do que foi entregue antes de concluir.")
    obj.status = status
    obj.concluida_em = timezone.now() if status == "CONCLUIDA" else None
    obj.full_clean()
    obj.save()
    return obj


@transaction.atomic
def apontar(tarefa, usuario, data, horas, descricao):
    # Serializa os apontamentos do mesmo usuário para respeitar 24 horas/dia.
    Usuario.objects.select_for_update().get(pk=usuario.pk)
    obj = visiveis(usuario, tarefa.empresa).select_for_update().filter(pk=tarefa.pk).first()
    if obj is None:
        raise PermissionDenied
    validar(obj, usuario)
    if obj.status in ("CONCLUIDA", "CANCELADA"):
        raise ValidationError("Reabra a tarefa antes de apontar horas.")
    if isinstance(horas, float):
        raise ValidationError("Use horas decimais.")
    try:
        horas = Decimal(horas)
    except (ValueError, TypeError, ArithmeticError):
        raise ValidationError("Horas inválidas.")
    if not horas.is_finite() or horas <= 0 or horas > 24 or horas != horas.quantize(Decimal("0.01")):
        raise ValidationError("Informe entre 0,01 e 24 horas, com até duas casas decimais.")
    if data > timezone.localdate() or data < obj.data_abertura:
        raise ValidationError("O apontamento deve ocorrer entre a abertura e hoje.")
    total = Apontamento.objects.filter(usuario=usuario, data=data).aggregate(v=Sum("horas"))["v"] or Decimal("0")
    if total + horas > 24:
        raise ValidationError("O total de apontamentos do dia não pode ultrapassar 24 horas.")
    if not descricao.strip():
        raise ValidationError("Descreva a atividade realizada.")
    apontamento = Apontamento(empresa=obj.empresa, tarefa=obj, usuario=usuario, data=data, horas=horas, descricao=descricao.strip())
    apontamento.full_clean()
    apontamento.save()
    return apontamento
