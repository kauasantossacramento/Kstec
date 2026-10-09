# Esquemas de produção

Fonte: pacote oficial `nfse-esquemas_xsd-v1-01-20260209.zip` disponível na
[documentação nacional](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/documentacao-atual).
Arquivos extraídos sem alteração.

O padrão de `TSSerieDPS` contém `^0{0,4}\d{1,5}$`. Libxml2 interpreta `^` e `$`
como caracteres literais em expressões XML Schema. O validador normaliza somente
esse padrão em memória para `0{0,4}[0-9]{1,5}`, preservando `maxLength=5`.
O gerador também exige série numérica entre 1 e 79999. A fonte permanece intacta.
