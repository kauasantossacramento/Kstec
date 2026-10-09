"""Recebível único da NFS-e autorizada em produção."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.fiscal.models import ConfiguracaoFiscal, NotaFiscal

from ..models import CategoriaFinanceira, CentroCusto, Lancamento
from .lancamentos import centro_contrato, validar


@transaction.atomic
def gerar_recebivel(nota):
    nota = NotaFiscal.objects.select_for_update().get(pk=nota.pk)
    if nota.status != "AUTORIZADA" or nota.ambiente != 1:
        raise ValidationError("Só notas autorizadas em produção geram recebível.")
    existente = Lancamento.objects.filter(nota_fiscal=nota).first()
    if existente:
        limpar_pendencia(nota)
        return existente
    config = ConfiguracaoFiscal.objects.filter(empresa=nota.empresa).first()
    categoria, _ = CategoriaFinanceira.objects.get_or_create(empresa=nota.empresa, nome="Vendas avulsas",
                    defaults={"tipo": "RECEITA", "grupo_dre": "RECEITA_BRUTA"})
    centro = centro_contrato(nota.contrato) if nota.contrato_id else CentroCusto.objects.get_or_create(
                        empresa=nota.empresa, nome="Administrativo")[0]
    vencimento = nota.vencimento_recebivel or nota.competencia + timedelta(days=config.prazo_recebimento_dias if config else 30)
    recebivel = Lancamento(empresa=nota.empresa, nota_fiscal=nota, tipo="RECEITA", pessoa=nota.tomador,
                    descricao=f"NFS-e {nota.numero_nfse} · {nota.tomador}", categoria=categoria, centro_custo=centro,
                    conta_bancaria=config.conta_recebimento if config else None, valor=nota.valor_liquido,
                    data_competencia=nota.competencia, data_vencimento=vencimento)
    validar(recebivel)
    recebivel.full_clean()
    recebivel.save()
    limpar_pendencia(nota)
    return recebivel


def limpar_pendencia(nota):
    if "recebivel_pendente" in nota.emissao_snapshot:
        nota.emissao_snapshot.pop("recebivel_pendente")
        nota.save()
