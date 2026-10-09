"""Tabelas fiscais mínimas (seção 1.2) e catálogo inicial da KS TEC.

As descrições de NBS aqui são provisórias: importe os anexos oficiais com `importar_tabelas_fiscais`.
A escolha final de NBS e cTribNac deve ser validada pelo contador (pendência 14.5 #3).
"""

from decimal import Decimal

from .models import (
    CategoriaCatalogo,
    CodigoNBS,
    CodigoServicoLC116,
    CodigoTributacaoNacional,
    CorrelacaoNBS,
    FaixaPreco,
    ItemCatalogo,
    VariacaoGrafica,
)

LC116 = {
    "01.01": "Análise e desenvolvimento de sistemas.",
    "01.03": "Processamento, armazenamento ou hospedagem de dados, textos, imagens, vídeos, páginas eletrônicas, "
             "aplicativos e sistemas de informação, entre outros formatos, e congêneres.",
    "01.05": "Licenciamento ou cessão de direito de uso de programas de computação.",
    "01.06": "Assessoria e consultoria em informática.",
    "01.07": "Suporte técnico em informática, inclusive instalação, configuração e manutenção de programas de "
             "computação e bancos de dados.",
    "01.08": "Planejamento, confecção, manutenção e atualização de páginas eletrônicas.",
    "13.03": "Fotografia e cinematografia, inclusive revelação, ampliação, cópia, reprodução, trucagem e congêneres.",
    "13.05": "Composição gráfica, inclusive confecção de impressos gráficos, fotocomposição, clicheria, zincografia, "
             "litografia e fotolitografia, exceto se destinados a posterior operação de comercialização ou "
             "industrialização.",
    "17.06": "Propaganda e publicidade, inclusive promoção de vendas, planejamento de campanhas ou sistemas de "
             "publicidade, elaboração de desenhos, textos e demais materiais publicitários.",
}

NBS = {
    "115021000": "Serviços de projeto e desenvolvimento de software (provisório)",
    "115022000": "Serviços de desenvolvimento de software customizado (provisório)",
    "115023000": "Serviços de projeto e desenvolvimento de páginas eletrônicas (provisório)",
    "115061000": "Serviços de hospedagem de sites (provisório)",
    "115062100": "Software como serviço — SaaS (provisório)",
    "115062200": "Infraestrutura como serviço — IaaS (provisório)",
    "111032200": "Licenciamento de direitos de uso de programas de computador (provisório)",
    "115011000": "Serviços de consultoria em tecnologia da informação (provisório)",
    "115013000": "Serviços de suporte técnico em tecnologia da informação (provisório)",
    "115080000": "Serviços de manutenção de programas de computador (provisório)",
}

CORRELACOES = [
    ("01.01", "115022000"), ("01.01", "115021000"),
    ("01.03", "115062100"), ("01.03", "115061000"), ("01.03", "115062200"),
    ("01.05", "111032200"), ("01.06", "115011000"),
    ("01.07", "115013000"), ("01.07", "115080000"), ("01.08", "115023000"),
]

CATEGORIAS = [
    ("Serviços de TI", "SERVICO_TI", "server"), ("Gráfica", "SERVICO_GRAFICO", "package"),
    ("Audiovisual", "AUDIOVISUAL", "eye"), ("Social media", "SOCIAL_MEDIA", "send"),
]

ITENS = [
    # sku, nome, categoria, unidade, preço, lc116, nbs
    ("TI-DEV", "Desenvolvimento de sistema sob medida", "Serviços de TI", "HORA", "150", "01.01", "115022000"),
    ("TI-SAAS", "Sistema em nuvem (SaaS) — licença mensal com hospedagem", "Serviços de TI", "MES", "1500", "01.03",
     "115062100"),
    ("TI-HOST", "Hospedagem de site/sistema", "Serviços de TI", "MES", "200", "01.03", "115061000"),
    ("TI-SUP", "Suporte técnico e manutenção de sistemas", "Serviços de TI", "MES", "2500", "01.07", "115013000"),
    ("TI-SITE", "Criação e manutenção de site institucional", "Serviços de TI", "UN", "3500", "01.08", "115023000"),
    ("TI-CONS", "Consultoria em tecnologia da informação", "Serviços de TI", "HORA", "180", "01.06", "115011000"),
    ("TI-LIC", "Licenciamento de uso de software", "Serviços de TI", "MES", "800", "01.05", "111032200"),
    ("SM-MENSAL", "Gestão de redes sociais (social media)", "Social media", "MES", "1200", "17.06", None),
    ("AV-VIDEO", "Produção audiovisual (vídeo institucional)", "Audiovisual", "UN", "2500", "13.03", None),
    ("GR-CARTAO", "Cartão de visita personalizado", "Gráfica", "UN", "0.90", "13.05", None),
]


def seed(empresa):
    for item, desc in LC116.items():
        CodigoServicoLC116.objects.get_or_create(item=item, defaults={"descricao": desc})
        it, sub = item.split(".")
        CodigoTributacaoNacional.objects.get_or_create(
            codigo=f"{it}{sub}01", defaults={"item": it, "subitem": sub, "desdobro": "01", "descricao": desc})
    for cod, desc in NBS.items():
        CodigoNBS.objects.get_or_create(codigo=cod, defaults={"codigo_mascarado": CodigoNBS.mascarar(cod),
                                                               "descricao": desc})
    for item, nbs in CORRELACOES:
        CorrelacaoNBS.objects.get_or_create(item_lc116=item, nbs=nbs)

    cats = {}
    for nome, tipo, icone in CATEGORIAS:
        cats[nome], _ = CategoriaCatalogo.objects.get_or_create(empresa=empresa, nome=nome,
                                                                defaults={"tipo": tipo, "icone": icone})
    criados = 0
    for sku, nome, cat, un, preco, lc, nbs in ITENS:
        if ItemCatalogo.objects.filter(empresa=empresa, codigo_interno=sku).exists():
            continue
        it, sub = lc.split(".")
        item = ItemCatalogo.objects.create(
            empresa=empresa, codigo_interno=sku, nome=nome, categoria=cats[cat], unidade=un, preco_base=Decimal(preco),
            item_lc116=CodigoServicoLC116.objects.get(item=lc),
            codigo_tributacao_nacional=CodigoTributacaoNacional.objects.get(codigo=f"{it}{sub}01"),
            nbs=CodigoNBS.objects.filter(codigo=nbs).first() if nbs else None,
        )
        criados += 1
        if sku == "GR-CARTAO":
            for qmin, qmax, p in [(100, 499, "0.90"), (500, 999, "0.55"), (1000, None, "0.38")]:
                FaixaPreco.objects.create(empresa=empresa, item=item, quantidade_min=qmin, quantidade_max=qmax,
                                          preco_unitario=Decimal(p))
            for atr, opc, tipo, val in [("PAPEL", "Couché 300g", "POR_UNIDADE", "0.05"),
                                        ("CORES", "4x4 (frente e verso coloridos)", "POR_UNIDADE", "0.08"),
                                        ("ACABAMENTO", "Verniz localizado", "PERCENTUAL", "20"),
                                        ("LAMINACAO", "Laminação fosca", "PERCENTUAL", "15"),
                                        ("CORTE", "Faca especial (cantos arredondados)", "FIXO", "50")]:
                VariacaoGrafica.objects.create(empresa=empresa, item=item, atributo=atr, opcao=opc, acrescimo_tipo=tipo,
                                               acrescimo_valor=Decimal(val))
    return f"{criados} item(ns) de catálogo"
