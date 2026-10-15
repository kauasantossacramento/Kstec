"""Recibo de prestação de serviços de uma NFS-e autorizada: valor por extenso, dados para pagamento e PIX
"copia e cola" com QR Code. Assinado digitalmente (carimbo sobre o nome da empresa) e arquivado na nota.

Enquanto o recebível não está pago, o recibo declara o serviço e o valor e condiciona a quitação à confirmação do
pagamento; depois da baixa, declara o recebimento (data e forma).
"""

import re

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.extenso import reais
from apps.core.models import Anexo
from apps.core.pdf import renderizar_pdf
from apps.core.validadores import formatar_doc, so_digitos
from apps.faturamento.services.calendario import mes_extenso
from apps.financeiro import pix

from ..models import ConfiguracaoFiscal, NotaFiscal


def descricao_servico(nota):
    """Objeto do serviço a partir da discriminação, sem PIX, sem a competência (já citada) e sem "Prestação de serviços de"."""
    texto = re.split(r"\n?\s*Chave PIX", nota.discriminacao or "", flags=re.IGNORECASE)[0]
    texto = re.sub(r"\s*Compet[êe]ncia\s*:[^.\n]*\.?", "", texto, flags=re.IGNORECASE)
    texto = " ".join(texto.split()).strip(" /.")
    texto = re.sub(r"^presta[çc][ãa]o de servi[çc]os?\s+(t[ée]cnicos?\s+especializados?\s*[-–]?\s*)?(de\s+)?", "", texto,
                   flags=re.IGNORECASE)
    return texto[:1].lower() + texto[1:] if texto[:2] != texto[:2].upper() else texto


def documento(pessoa):
    doc = so_digitos(getattr(pessoa, "cpf_cnpj", ""))
    return f"{'CNPJ' if len(doc) == 14 else 'CPF'} {formatar_doc(doc)}" if len(doc) in (11, 14) else ""


def contexto(nota):
    from apps.financeiro.models import ContaBancaria, Lancamento

    lanc = Lancamento.objects.filter(nota_fiscal=nota).exclude(status="CANCELADO").select_related("conta_bancaria").first()
    config = ConfiguracaoFiscal.objects.select_related("conta_recebimento").filter(empresa=nota.empresa).first()
    conta = (lanc.conta_bancaria if lanc and lanc.conta_bancaria_id else None) \
        or (config.conta_recebimento if config else None) \
        or ContaBancaria.objects.filter(empresa=nota.empresa, ativo=True).first()
    chave = (getattr(conta, "chave_pix", "") if conta else "") or nota.empresa.cnpj
    valor = lanc.valor if lanc else nota.valor_liquido
    pago = bool(lanc and lanc.status == "PAGO")
    cidade = (nota.empresa.endereco.municipio_nome if nota.empresa.endereco_id else "") or "Valenca"
    payload = "" if pago else pix.copia_e_cola(chave, nota.empresa.razao_social, cidade, valor,
                                               txid=f"NFSE{nota.numero_nfse}")
    return {"nota": nota, "empresa": nota.empresa, "tomador": nota.tomador, "documento_tomador": documento(nota.tomador),
            "descricao": descricao_servico(nota), "competencia": mes_extenso(nota.competencia), "valor": valor,
            "valor_extenso": reais(valor), "retencoes": nota.valor_servicos - nota.valor_liquido,
            "lancamento": lanc, "pago": pago, "conta": conta, "chave_pix": chave,
            "chave_pix_formatada": formatar_doc(chave) if chave.isdigit() and len(chave) in (11, 14) else chave,
            "pix_copia_cola": payload, "pix_qr": pix.qr_data_uri(payload) if payload else "", "emitido_em": timezone.localdate()}


def gerar(nota):
    """Gera, assina e arquiva o recibo na nota. Retorna o Anexo."""
    from apps.core.services.assinatura import assinar_se_possivel

    nota = NotaFiscal.objects.select_related("empresa__endereco", "tomador", "contrato").get(pk=nota.pk)
    if nota.status != NotaFiscal.Status.AUTORIZADA:
        raise ValidationError("Recibo só para NFS-e autorizada.")
    ctx = contexto(nota)
    pdf = renderizar_pdf("pdf/recibo.html", {**ctx, "data_documento": ctx["emitido_em"]})
    pdf, titular = assinar_se_possivel(pdf, nota.empresa, f"Recibo da NFS-e {nota.numero_nfse}")
    return Anexo.criar(nota, f"recibo_nfse_{nota.numero_nfse}.pdf", pdf, retencao_anos=5,
                       descricao="Recibo de prestação de serviços" + (f" · assinado por {titular}" if titular else ""))
