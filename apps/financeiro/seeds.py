from .models import CategoriaFinanceira, CentroCusto


def seed(empresa):
    for nome in ("Contratos públicos", "Contratos privados", "Vendas avulsas", "Gráfica", "Audiovisual"):
        CategoriaFinanceira.objects.get_or_create(empresa=empresa, nome=nome,
            defaults={"tipo": "RECEITA", "grupo_dre": "RECEITA_BRUTA"})
    for nome, grupo in [("Infraestrutura", "CUSTO_SERVICO"), ("Software, licenças e APIs", "CUSTO_SERVICO"),
        ("Pessoal e terceiros", "CUSTO_SERVICO"), ("Impostos", "IMPOSTOS"), ("Deslocamento", "CUSTO_SERVICO"),
        ("Material gráfico", "CUSTO_SERVICO"), ("Marketing", "DESPESA_OPERACIONAL"),
        ("Administrativas", "DESPESA_OPERACIONAL"), ("Tarifas bancárias", "DESPESA_FINANCEIRA")]:
        CategoriaFinanceira.objects.get_or_create(empresa=empresa, nome=nome,
            defaults={"tipo": "DESPESA", "grupo_dre": grupo})
    CentroCusto.objects.get_or_create(empresa=empresa, nome="Administrativo")
    from apps.contratos.models import Contrato

    from .services.lancamentos import centro_contrato

    for contrato in Contrato.objects.filter(empresa=empresa):
        centro_contrato(contrato)
    return "Categorias e centros de custo cadastrados."
