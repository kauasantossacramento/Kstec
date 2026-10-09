from apps.core.crud import Coluna, Crud, DetalheGenerico

from .forms import ContatoForm, PessoaForm
from .models import Contato, Pessoa


class PessoaDetalhe(DetalheGenerico):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["contatos"] = self.object.contatos.all()
        return ctx


CRUD_PESSOA = Crud(
    model=Pessoa, prefixo="pessoa", namespace="cadastros", feminino=True, titulo="Pessoa",
    subtitulo="Clientes, órgãos públicos e fornecedores em um cadastro único.",
    colunas=[Coluna("Nome / razão social", "razao_social", link=True), Coluna("CPF/CNPJ", "cpf_cnpj", "doc"),
             Coluna("Cidade", "endereco.municipio_nome"), Coluna("Órgão público", "e_orgao_publico", "bool"),
             Coluna("Cliente", "eh_cliente", "bool"), Coluna("Fornecedor", "eh_fornecedor", "bool")],
    form_class=PessoaForm, busca=["razao_social", "nome_fantasia", "cpf_cnpj"],
    filtros=["eh_cliente", "eh_fornecedor", "e_orgao_publico"], ordenacao=["razao_social"],
    template_detalhe="cadastros/pessoa_detalhe.html", template_form="cadastros/pessoa_form.html",
    select_related=["endereco"],
    campos_detalhe=["cpf_cnpj", "razao_social", "nome_fantasia", "inscricao_municipal", "inscricao_estadual",
                    "email", "email_nf", "telefone", "e_orgao_publico", "esfera", "optante_simples",
                    "situacao_cadastral", "data_abertura", "cnae_principal", "descricao_cnae", "natureza_juridica", "porte",
                    "endereco", "observacoes"],
)

CRUD_CONTATO = Crud(
    model=Contato, prefixo="contato", namespace="cadastros",
    colunas=[Coluna("Nome", "nome", link=True), Coluna("Cargo", "cargo"), Coluna("Pessoa", "pessoa"),
             Coluna("E-mail", "email"), Coluna("Recebe relatórios", "recebe_relatorios", "bool")],
    form_class=ContatoForm, busca=["nome", "email", "pessoa__razao_social"], ordenacao=["nome"],
    select_related=["pessoa"], anexos=False,
)
