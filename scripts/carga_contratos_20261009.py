"""Carga única em produção (09/10/2026): CONMAC, INVICTA e Bom Jesus da Lapa; documentos assinados; e-mails.

Executar DENTRO do contêiner web, com os arquivos em /tmp/carga/ e as senhas SMTP em variáveis de ambiente:
    docker exec -e SMTP_GESTAO=... -e SMTP_FINANCEIRO=... kscentral-web python /tmp/carga/carga.py
Idempotente: rodar de novo não duplica contratos, agendas, documentos nem contas.
"""
import os
import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import django

sys.path.insert(0, os.environ.get("KS_RAIZ", "/app"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.db import transaction  # noqa: E402

from apps.cadastros.models import Pessoa  # noqa: E402
from apps.catalogo.models import ItemCatalogo  # noqa: E402
from apps.contratos.models import Contrato, DocumentoContrato  # noqa: E402
from apps.core import contexto  # noqa: E402
from apps.core.models import Anexo, ContaEmail, Empresa, Endereco, Segredo  # noqa: E402
from apps.core.services.brasilapi import ConsultaIndisponivel, consultar_cnpj  # noqa: E402
from apps.faturamento.models import AgendaFaturamento  # noqa: E402
from apps.faturamento.services import ciclos  # noqa: E402
from apps.financeiro.models import CentroCusto  # noqa: E402
from apps.financeiro.services.lancamentos import centro_contrato  # noqa: E402
from apps.fiscal.models import PerfilFiscal  # noqa: E402
from apps.sla.services.alertas_email import configuracao as config_alertas  # noqa: E402

PASTA = Path(os.environ.get("CARGA_PASTA", "/tmp/carga"))
PIX = "Chave PIX: 62501281000113 / Banco do Brasil / KS TEC SOLUÇÕES DE TECNOLOGIA LTDA"
empresa = Empresa.objects.order_by("criado_em").first()
contexto.definir(empresa, None)
sem_retencao = PerfilFiscal.objects.get(empresa=empresa, nome="KS TEC — ISS 2% sem retenção")
item = {c: ItemCatalogo.objects.get(empresa=empresa, codigo_interno=c) for c in ("TI-DEV", "TI-SUP", "TI-LIC")}


def pessoa(cnpj, razao, **extra):
    existente = Pessoa.objects.filter(empresa=empresa, cpf_cnpj=cnpj).first() if cnpj else \
        Pessoa.objects.filter(empresa=empresa, razao_social=razao).first()
    if existente:
        return existente
    dados, end = {"razao_social": razao}, None
    if cnpj:
        try:
            r = consultar_cnpj(cnpj)
            dados = {k: r[k] for k in ("razao_social", "nome_fantasia", "email", "telefone", "situacao_cadastral",
                                       "cnae_principal", "descricao_cnae", "natureza_juridica", "porte") if r.get(k)}
            if r.get("data_abertura"):
                dados["data_abertura"] = date.fromisoformat(r["data_abertura"])
            e = r["endereco"]
            if e.get("cep") and e.get("municipio_ibge"):
                end = Endereco.objects.create(**{k: e[k] for k in ("cep", "tipo_logradouro", "logradouro", "numero",
                                              "complemento", "bairro", "municipio_ibge", "municipio_nome", "uf")})
        except ConsultaIndisponivel as erro:
            print("  consulta CNPJ indisponível:", erro)
    dados.update(extra)
    return Pessoa.objects.create(empresa=empresa, cpf_cnpj=cnpj, endereco=end, eh_cliente=True, **dados)


def anexar(contrato, arquivo, tipo, competencia, titulo, assinado=True, observacao=""):
    caminho = PASTA / arquivo
    if not caminho.exists():
        print("  (arquivo ausente)", arquivo)
        return
    if DocumentoContrato.objects.filter(contrato=contrato, titulo=titulo).exists():
        return
    anexo = Anexo.criar(contrato, caminho.name, caminho.read_bytes(), descricao=titulo, retencao_anos=5)
    DocumentoContrato.objects.create(empresa=empresa, contrato=contrato, tipo=tipo, competencia=competencia,
                                     titulo=titulo, assinado=assinado, anexo=anexo, observacao=observacao)
    print("  documento:", titulo)


with transaction.atomic():
    # ---------------- clientes ----------------
    bjl = pessoa("14105183000114", "MUNICÍPIO DE BOM JESUS DA LAPA", e_orgao_publico=True, esfera="MUNICIPAL",
                 email_nf="licitacao@bomjesusdalapa.ba.gov.br", telefone="(77) 3481-3374")
    if not bjl.endereco_id:
        bjl.endereco = Endereco.objects.create(cep="47600000", tipo_logradouro="Praça", logradouro="Marechal Deodoro da Fonseca",
                                               numero="S/N", bairro="Centro", municipio_ibge="2903904",
                                               municipio_nome="Bom Jesus da Lapa", uf="BA")
        bjl.save()
    conmac = pessoa("17449551000130", "CONMAC SERVICOS CONTABEIS, TREINAMENTO E DESENVOLVIMENTO LTDA")
    invicta = pessoa("57361987000197", "INVICTA ASSESSORIA E CONSULTORIA",
                     observacoes="Cliente também conhecido como SDL. Contrato desde 10/06/2026, vencimento todo dia 10.")

    # ---------------- contratos ----------------
    NOVOS = [
        dict(numero="216/2026", cliente=bjl, modalidade="DISPENSA", processo_administrativo="216/2026",
             fundamento_legal="Dispensa nº 045/2026 · Lei 14.133/2021, art. 75, II",
             objeto="Fornecimento, implantação, personalização, migração de acervo, capacitação e suporte técnico "
                    "continuado de plataforma de Nuvem Privada Municipal (2 TB), sob subdomínio institucional.",
             data_assinatura=date(2026, 9, 22), vigencia_inicio=date(2026, 9, 22), vigencia_fim=date(2027, 9, 21),
             valor_global=Decimal("24600"), valor_mensal=Decimal("2050"), dia_faturamento=5, prazo_pagamento_dias=30,
             cor="#7C3AED", _item=item["TI-LIC"], _inicio=date(2026, 10, 1), _ref="MES_ANTERIOR", _dia=5,
             _venc=("PRAZO", 30, None), _arquivo="CONTRATO 216-2026 DRIVE.pdf",
             _disc=("Licenciamento de uso da plataforma de Nuvem Privada Municipal, com armazenamento de 2 TB, suporte "
                    "técnico continuado e backup automatizado. Contrato nº {contrato} — Dispensa nº 045/2026 — Processo "
                    "Administrativo nº 216/2026. Competência: {mes_nome}/{ano} ({parcela}º mês de {total_parcelas}).\n\n" + PIX)),
        dict(numero="CONMAC-2026", cliente=conmac, modalidade="PRIVADO",
             fundamento_legal="Contrato privado de prestação de serviços",
             objeto="Manutenção, suporte técnico, atualização e desenvolvimento de sistemas: Painel de Links, Site "
                    "Institucional, Sistema de Arquivos em Nuvem (servidor), Sistema de Gestão Inteligente da CONMAC, "
                    "gestão de mídia social e desenvolvimento sob medida.",
             data_assinatura=date(2026, 9, 10), vigencia_inicio=date(2026, 9, 10), vigencia_fim=date(2027, 9, 9),
             valor_global=Decimal("42000"), valor_mensal=Decimal("3500"), dia_faturamento=1, prazo_pagamento_dias=9,
             cor="#0EA5E9", _item=item["TI-SUP"], _inicio=date(2026, 9, 1), _ref="MES_ANTERIOR", _dia=1,
             _venc=("DIA_FIXO", 30, 10), _arquivo="Contrato de Prestação de Serviços - KS TEC x CONMAC.pdf",
             _obs="Valor e vigência informados pelo sócio em 09/10/2026 (R$ 3.500,00, 12 meses). A minuta em PDF traz "
                  "R$ 4.500,00 e prazo indeterminado — conferir a versão assinada.",
             _disc=("Prestação de serviços de manutenção, suporte técnico, atualização e desenvolvimento de sistemas "
                    "(Painel de Links, Site Institucional, Sistema de Arquivos em Nuvem e Sistema de Gestão Inteligente). "
                    "Competência: {mes_nome}/{ano}.\n\n" + PIX)),
        dict(numero="INVICTA-2026", cliente=invicta, modalidade="PRIVADO",
             fundamento_legal="Contrato privado de prestação de serviços",
             objeto="Prestação de serviços de desenvolvimento de sistema, suporte em tecnologia da informação e "
                    "licenciamento de sistema da KS TEC.",
             data_assinatura=date(2026, 6, 10), vigencia_inicio=date(2026, 6, 10), vigencia_fim=date(2027, 6, 9),
             valor_global=Decimal("60000"), valor_mensal=Decimal("5000"), dia_faturamento=1, prazo_pagamento_dias=9,
             cor="#F97316", _item=item["TI-DEV"], _inicio=date(2026, 6, 1), _ref="MES_ANTERIOR", _dia=1,
             _venc=("DIA_FIXO", 30, 10), _arquivo=None,
             _obs="Vigência de 12 meses assumida (não informada). Contrato também chamado de SDL.",
             _disc=("Prestação de serviços de desenvolvimento de sistema, suporte em tecnologia da informação e "
                    "licenciamento de sistema da KS TEC. Competência: {mes_nome}/{ano}.\n\n" + PIX)),
    ]
    contratos = {}
    for dados in NOVOS:
        extra = {k: dados.pop(k) for k in list(dados) if k.startswith("_")}
        c, criado = Contrato.objects.get_or_create(empresa=empresa, numero=dados["numero"], cliente=dados["cliente"],
            defaults=dict(dados, forma_faturamento="MENSAL", status="VIGENTE", exige_relatorio_atividades=False,
                          discriminacao_padrao=extra["_disc"]))
        print(("criado " if criado else "já existia ") + str(c))
        centro_contrato(c)
        if extra.get("_arquivo"):
            anexar(c, extra["_arquivo"], "CONTRATO", None, f"Contrato {c.numero}", observacao=extra.get("_obs", ""))
        tipo_v, prazo, dia_v = extra["_venc"]
        AgendaFaturamento.objects.get_or_create(contrato=c, defaults=dict(
            empresa=empresa, item_catalogo=extra["_item"], perfil=sem_retencao, valor=c.valor_mensal,
            referencia=extra["_ref"], dia_emissao=extra["_dia"], hora_emissao=time(8), dia_util=True,
            tipo_vencimento=tipo_v, prazo_dias=prazo, dia_vencimento=dia_v, modo="RASCUNHO", inicio=extra["_inicio"],
            ativa_desde=date(2026, 1, 1), observacoes=(extra.get("_obs", "") + " Modo rascunho até o contador confirmar "
                                                       "serviço e tributação deste cliente.").strip()))
        contratos[c.numero] = c

    # ---------------- documentos assinados dos contratos da Prefeitura de Valença ----------------
    por_numero = {c.numero: c for c in Contrato.objects.filter(empresa=empresa)}
    DOCS = [
        ("022/2026", "fibro_jun_planilha.pdf", "PLANILHA_CUSTOS", date(2026, 6, 1), "Planilha de custos — Fibromialgia · junho/2026 (assinada)"),
        ("022/2026", "fibro_jun_relatorio.pdf", "RELATORIO_ATIVIDADES", date(2026, 6, 1), "Relatório de atividades — SIDEC · junho/2026 (assinado)"),
        ("022/2026", "fibro_jul_planilha.pdf", "PLANILHA_CUSTOS", date(2026, 7, 1), "Planilha de custos — Fibromialgia · julho/2026 (assinada)"),
        ("022/2026", "fibro_jul_relatorio.pdf", "RELATORIO_ATIVIDADES", date(2026, 7, 1), "Relatório de atividades — SIDEC · julho/2026 (assinado)"),
        ("136/2026", "staas_jun_planilha.pdf", "PLANILHA_CUSTOS", date(2026, 6, 1), "Planilha de custos — STaaS · junho/2026 (assinada)"),
        ("136/2026", "staas_jun_relatorio.pdf", "RELATORIO_ATIVIDADES", date(2026, 6, 1), "Relatório de atividades — STaaS · junho/2026 (assinado)"),
        ("136/2026", "staas_sla.pdf", "RELATORIO_SLA", date(2026, 6, 1), "Relatório de SLA — STaaS (arquivo nomeado Agosto/2026, guardado na pasta de junho)"),
        ("116/2026", "sigal_jun_planilha.pdf", "PLANILHA_CUSTOS", date(2026, 6, 1), "Planilha de custos — SIGAL · junho/2026 (assinada)"),
        ("116/2026", "sigal_jun_relatorio.pdf", "RELATORIO_ATIVIDADES", date(2026, 6, 1), "Relatório de atividades — SIGAL · maio/junho 2026 (assinado)"),
        ("116/2026", "sigal_jul_planilha.pdf", "PLANILHA_CUSTOS", date(2026, 7, 1), "Planilha de custos — SIGAL · julho/2026 (arquivo nomeado junho; assinada)"),
        ("116/2026", "sigal_jul_relatorio.pdf", "RELATORIO_ATIVIDADES", date(2026, 7, 1), "Relatório de atividades — SIGAL · julho/2026 (assinado)"),
        ("072/2026", "justificativa_atraso.pdf", "OFICIO", None, "Justificativa de atraso do envio das notas fiscais (assinada)"),
    ]
    for numero, arquivo, tipo, comp, titulo in DOCS:
        if numero in por_numero:
            anexar(por_numero[numero], arquivo, tipo, comp, titulo)
    # extratos já anexados na migração viram documentos da central
    for c in por_numero.values():
        for a in Anexo.objects.filter(object_id=str(c.pk), nome__icontains="xtrato") | \
                Anexo.objects.filter(object_id=str(c.pk), nome__icontains="Processo Administrativo"):
            if not DocumentoContrato.objects.filter(anexo=a).exists():
                DocumentoContrato.objects.create(empresa=empresa, contrato=c, tipo="CONTRATO", titulo=a.nome.rsplit(".", 1)[0],
                                                 assinado=True, anexo=a)
                print("  extrato na central:", a.nome)

    # ---------------- contas de e-mail e alertas ----------------
    for finalidade, email, nome, variavel in (("ALERTAS", "gestao@kstec.online", "KS TEC · Gestão", "SMTP_GESTAO"),
                                              ("DOCUMENTOS", "financeiro@kstec.online", "KS TEC · Financeiro", "SMTP_FINANCEIRO")):
        senha = os.environ.get(variavel, "").strip()
        conta, _ = ContaEmail.objects.get_or_create(empresa=empresa, finalidade=finalidade, defaults=dict(
            email=email, nome_remetente=nome, host="smtp.hostinger.com", porta=587, seguranca="STARTTLS", ativo=False))
        if senha:
            conta.senha = Segredo.criar(f"SMTP · {email}", senha, "INTEGRACAO", empresa)
            conta.ativo = True
            conta.save()
            print("  conta de e-mail ativa:", email)
    alertas = config_alertas(empresa)
    if not alertas.emails_gerais:
        alertas.emails_gerais = "kaua@kstec.online"
        alertas.save()
    CentroCusto.objects.filter(empresa=empresa, contrato__isnull=True, nome="Administrativo").update(ratear=True)

for c in contratos.values():
    ciclos.planejar(c.agenda_faturamento)
    print(c.numero, [(f"{x.competencia:%m/%Y}", x.status) for x in c.agenda_faturamento.ciclos.order_by("competencia")])
