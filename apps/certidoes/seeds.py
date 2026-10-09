from .models import TipoCertidao

TIPOS = [
    ("CND Federal conjunta (RFB/PGFN)", "Receita Federal / PGFN", "FEDERAL",
     "https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PJ/Emitir", 180, True),
    ("CRF FGTS", "Caixa Econômica Federal", "FEDERAL", "https://consulta-crf.caixa.gov.br/consultacrf/", 30, True),
    ("CNDT — Certidão Negativa de Débitos Trabalhistas", "TST", "TRABALHISTA",
     "https://cndt-certidao.tst.jus.br/inicio.faces", 180, True),
    ("Certidão de Regularidade Fiscal Estadual", "SEFAZ-BA", "ESTADUAL",
     "https://servicosweb.sefaz.ba.gov.br/sistemas/DSCRE/Modulos/Publico/EmissaoCertidao.aspx", 60, True),
    ("Certidão Negativa de Débitos Municipais", "Prefeitura de Valença", "MUNICIPAL", "", 90, True),
    ("Certidão de Falência e Recuperação Judicial", "TJBA", "JUDICIAL", "https://www.tjba.jus.br/", 90, True),
    ("Certidão Simplificada", "JUCEB", "ESTADUAL", "https://www.juceb.ba.gov.br/", 90, False),
    ("Consulta Consolidada TCU / CEIS / CNEP", "TCU", "FEDERAL", "https://certidoes-apf.apps.tcu.gov.br/", 30, False),
    ("Alvará de funcionamento", "Prefeitura de Valença", "MUNICIPAL", "", 365, False),
    ("Inscrição Municipal (Cadastro)", "Prefeitura de Valença", "MUNICIPAL", "", 365, False),
]


def seed(empresa):
    criados = 0
    for nome, orgao, esfera, url, dias, obrig in TIPOS:
        _, novo = TipoCertidao.objects.get_or_create(
            empresa=empresa, nome=nome,
            defaults={"orgao_emissor": orgao, "esfera": esfera, "url_emissao": url,
                      "validade_padrao_dias": dias, "obrigatoria_habilitacao": obrig},
        )
        criados += novo
    return f"{criados} tipo(s) de certidão"
