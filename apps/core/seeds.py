"""Sementes do núcleo: empresa KS TEC e papéis (Fase 1)."""

from django.contrib.auth.models import Group

from .models import Empresa, Endereco, Parametro, Usuario

KS_TEC = {
    "razao_social": "KS TEC SOLUCOES DE TECNOLOGIA LTDA",
    "nome_fantasia": "KS TEC",
    "cnpj": "62501281000113",
    "regime_tributario": Empresa.Regime.SIMPLES,
    "optante_simples": True,
    "regime_especial_tributacao": 6,
    "municipio_ibge": "2932903",
    "site": "https://kstec.online",
    "cor_primaria": "#0016E1",
}

PARAMETROS = {
    "certidoes.dias_alerta": ([30, 15, 7, 0], "Dias antes do vencimento para alertar certidões."),
    "contratos.dias_alerta_vigencia": ([90, 60, 30], "Alertas de fim de vigência contratual."),
    "contratos.percentual_alerta_saldo": (20, "Alerta quando o saldo do contrato ficar abaixo deste %."),
    "sla.intervalo_minutos": (5, "Intervalo padrão de verificação dos sistemas."),
    "sla.peso_incidente_parcial": (0.5, "Peso dos incidentes PARCIAL no cálculo de disponibilidade."),
    "fiscal.erros_permitem_fallback": (["E0001", "E0002", "L999"],
                                       "Códigos de erro que liberam fallback automático entre canais."),
    "ia.limite_mensal_brl": (50, "Limite mensal de custo de IA (R$)."),
}


def seed(empresa=None, **kw):
    for papel in Usuario.PAPEIS:
        Group.objects.get_or_create(name=papel)
    empresa = Empresa.objects.filter(cnpj=KS_TEC["cnpj"]).first()
    if empresa is None:
        end = Endereco.objects.create(cep="45400000", logradouro="A definir", bairro="Centro", municipio_ibge="2932903",
                                      municipio_nome="Valença", uf="BA")
        empresa = Empresa.objects.create(endereco=end, **KS_TEC)
    for chave, (valor, desc) in PARAMETROS.items():
        if not Parametro.objects.filter(empresa=empresa, chave=chave).exists():
            Parametro.objects.create(empresa=empresa, chave=chave, valor=valor, descricao=desc)
    Usuario.objects.filter(empresa__isnull=True).update(empresa=empresa)
    return empresa
