"""Composição mensal declarada, BDI e exportações da versão aprovada."""
import io
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.properties import CalcProperties

from apps.contratos.models import Contrato
from apps.core.models import Anexo
from apps.core.pdf import renderizar_pdf
from apps.core.permissoes import exigir_escrita

from ..models import ItemCusto, PlanilhaCustos

PARAMETROS = ("administracao_central", "seguro_garantia", "risco", "despesas_financeiras", "lucro", "tributos")


@transaction.atomic
def nova_planilha(contrato, competencia):
    contrato = Contrato.objects.select_for_update().get(pk=contrato.pk)
    competencia = competencia.replace(day=1)
    versao = (PlanilhaCustos.objects.filter(contrato=contrato, competencia=competencia).aggregate(v=Max("versao"))["v"] or 0) + 1
    return PlanilhaCustos.objects.create(empresa=contrato.empresa, contrato=contrato, competencia=competencia, versao=versao)


def texto_seguro(valor):
    # Conteúdo cadastrado é texto, não fórmula executável no Excel.
    return "'" + valor if valor.startswith(("=", "+", "-", "@")) else valor


def exportar_xlsx(planilha):
    wb = Workbook()
    ws = wb.active
    ws.title = "Custos"
    wb.calculation = CalcProperties(fullCalcOnLoad=True)
    ws.append([f"KS TEC · Planilha de custos · Contrato {planilha.contrato.numero}"])
    ws.merge_cells("A1:I1")
    ws.append([f"Competência {planilha.competencia:%m/%Y} · versão {planilha.versao} · composição declarada"])
    ws.merge_cells("A2:I2")
    ws.append(["Grupo", "Descrição", "Unidade", "Quantidade", "Valor unitário", "Rateio", "Periodicidade", "Custo mensal", "Fonte"])
    itens = list(planilha.itens.order_by("criado_em", "pk"))
    calculados = {}
    for linha, item in enumerate(itens, 4):
        ws.append([item.get_grupo_display(), texto_seguro(item.descricao), texto_seguro(item.unidade), item.quantidade,
                   item.valor_unitario, item.rateio_pct / 100, item.get_periodicidade_display(),
                   f"=ROUND(D{linha}*E{linha}*F{linha}/{12 if item.periodicidade == 'ANUAL' else 1},2)", texto_seguro(item.fonte)])
        for coluna in ("D", "E", "H"):
            ws[f"{coluna}{linha}"].number_format = '#,##0.00'
        ws[f"F{linha}"].number_format = "0.00%"
        calculados[f"H{linha}"] = item.valor_mensal
    fim = 3 + len(itens)
    total = fim + 2
    ws.cell(total, 7, "Custo direto mensal")
    ws.cell(total, 8, f"=SUM(H4:H{fim})")
    calculados[f"H{total}"] = sum((item.valor_mensal for item in itens), Decimal(0))
    for indice, campo in enumerate(PARAMETROS, total + 2):
        ws.cell(indice, 7, planilha._meta.get_field(campo).verbose_name)
        ws.cell(indice, 8, getattr(planilha, campo) / 100).number_format = "0.00%"
    a, s, r, df, lucro, i = [f"H{x}" for x in range(total + 2, total + 8)]
    bdi = total + 9
    ws.cell(bdi, 7, "BDI")
    ws.cell(bdi, 8, f"=(1+{a}+{s}+{r})*(1+{df})*(1+{lucro})/(1-{i})-1").number_format = "0.00%"
    calculados[f"H{bdi}"] = planilha.bdi
    ws.cell(bdi + 1, 7, "Preço mensal composto")
    ws.cell(bdi + 1, 8, f"=ROUND(H{total}*(1+H{bdi}),2)").number_format = '#,##0.00'
    calculados[f"H{bdi + 1}"] = (calculados[f"H{total}"] * (1 + planilha.bdi)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ws.cell(total, 8).number_format = '#,##0.00'
    ws.cell(bdi + 3, 1, texto_seguro(planilha.observacoes or "Fontes declaradas na coluna Fonte. Custo único apropriado nesta competência."))
    ws.merge_cells(start_row=bdi + 3, start_column=1, end_row=bdi + 3, end_column=9)
    ws.row_dimensions[bdi + 3].height = 40
    for col, largura in zip("ABCDEFGHI", (23, 45, 12, 14, 18, 12, 25, 20, 45), strict=True):
        ws.column_dimensions[col].width = largura
    for row in ws:
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if cell.row in (1, 3):
                cell.fill = PatternFill("solid", fgColor="061534")
                cell.font = Font(name="Calibri", color="FFFFFF", bold=True)
    for linha in range(4, fim + 1):
        ws.row_dimensions[linha].height = 44
    ws.freeze_panes = "D4"
    ws.auto_filter.ref = f"A3:I{fim}"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:3"
    buf = io.BytesIO()
    wb.save(buf)
    # Preserve as fórmulas e seus valores aprovados, inclusive para leitores que
    # não recalculam XLSX. O Excel recalcula quando a planilha é editada.
    saida = io.BytesIO()
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(buf) as origem, zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as destino:
        for arquivo in origem.infolist():
            conteudo = origem.read(arquivo.filename)
            if arquivo.filename == "xl/worksheets/sheet1.xml":
                raiz = ElementTree.fromstring(conteudo)
                for celula in raiz.iter(ns + "c"):
                    valor = calculados.get(celula.get("r"))
                    if valor is not None:
                        tag = celula.find(ns + "v")
                        if tag is None:
                            tag = ElementTree.SubElement(celula, ns + "v")
                        tag.text = str(valor)
                conteudo = ElementTree.tostring(raiz, encoding="utf-8", xml_declaration=True)
            destino.writestr(arquivo, conteudo)
    return saida.getvalue()


@transaction.atomic
def salvar_planilha(planilha, dados, linhas, usuario, aprovar=False):
    exigir_escrita(usuario, ["Financeiro"])
    atual = PlanilhaCustos.objects.select_for_update().get(pk=planilha.pk, empresa=usuario.empresa)
    if atual.status != "RASCUNHO":
        raise ValidationError("A planilha aprovada está preservada. Crie uma nova versão para alterar.")
    if not linhas:
        raise ValidationError("Cadastre ao menos um custo com fonte. Não são presumidos valores do contrato.")
    for campo in (*PARAMETROS, "observacoes"):
        setattr(atual, campo, dados[campo])
    atual.full_clean()
    atual.itens.all().delete()
    for dados_item in linhas:
        item = ItemCusto(empresa=atual.empresa, planilha=atual, **dados_item)
        item.full_clean()
        item.save()
    if aprovar:
        atual.status, atual.aprovado_por, atual.aprovado_em = "APROVADO", usuario, timezone.now()
        total = sum((i.valor_mensal for i in atual.itens.all()), Decimal(0))
        atual.xlsx = Anexo.criar(atual, f"custos_{atual.competencia:%Y%m}_v{atual.versao}.xlsx", exportar_xlsx(atual), retencao_anos=5)
        atual.pdf = Anexo.criar(atual, f"custos_{atual.competencia:%Y%m}_v{atual.versao}.pdf",
                      renderizar_pdf("pdf/custos.html", {"planilha": atual, "itens": atual.itens.all(), "total": total,
                             "bdi_pct": atual.bdi * 100, "preco": total * (1 + atual.bdi), "empresa": atual.empresa}), retencao_anos=5)
    atual.save()
    return atual
