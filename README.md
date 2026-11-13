# MasterFicha

Repositório pessoal de fichas de RPG. Cada ficha pertence a um RPG cadastrado e recebe um identificador UUID único. A ficha aceita história, atributos, poderes/habilidades, inventário e tags livres.

## Executar localmente

Requer Python 3.10 ou superior. A aplicação usa somente a biblioteca padrão do Python e SQLite.

```powershell
python server.py
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000). A primeira execução cria `data/masterficha.sqlite3`. Esse arquivo contém os dados da biblioteca e deve ser incluído no backup do usuário; não o apague para preservar as fichas.

## O que já funciona

- Cadastro de RPGs, cada um com identificador próprio.
- Criação e edição de fichas com nome, história, atributos flexíveis, poderes, itens de inventário e tags.
- Atributos aceitam fórmulas matemáticas e lógicas, referências entre parênteses e funções SE, E, OU, NAO, MÍNIMO, MÁXIMO, SOMA, MÉDIA, INT, TRUNCAR, RAIZ, ABS, ARRED, POTÊNCIA e MOD; o editor sugere atributos e funções enquanto a fórmula é digitada.
- Inventário separado para materiais de recursos em uma grade editável, com campos definidos pelo usuário e ordenação crescente/decrescente por qualquer coluna.
- A grade aceita até 30 campos e 200 linhas por ficha; os materiais existentes no inventário convencional são mantidos em sua própria seção.
- Cada poder pode ter um ou mais modificadores numéricos de atributo: soma, subtração, multiplicação ou divisão.
- Aba Poderes na ficha com um botão por habilidade; a seleção mostra uma simulação dos atributos atuais sem sobrescrever os valores base.
- Quando várias habilidades estão ativas, seus modificadores são aplicados na ordem em que os poderes aparecem na ficha.
- Os modificadores apontam para atributos cadastrados na própria ficha; o editor sugere os nomes disponíveis.
- Geração automática de identificadores UUID para as fichas.
- Abas individuais para resumo, treinos, missões e eventos de cada ficha.
- Registros com data, imagem PNG/JPEG/WebP (até 2 MB), descrição e ganhos opcionais de atributos.
- Exportação dos treinos, missões e eventos de uma ficha em ZIP com relatório HTML, CSV e arquivos originais das imagens de prova.
- Atributos atuais calculados com os ganhos guardados nos registros; fórmulas dependentes usam o valor atualizado dos atributos referenciados, e excluir um registro recalcula os totais.
- Busca por personagem, história, RPG, tag e ID; filtro por RPG.
- Exclusão de ficha com confirmação. RPG que ainda possui fichas não pode ser removido.
- Validação no servidor e persistência em SQLite.

## Escopo atual

Esta primeira versão é local e de usuário único: o servidor escuta em `127.0.0.1`, e os dados ficam no computador onde ele é executado. Não há autenticação, sincronização entre dispositivos, importação das planilhas existentes ou exportação de fichas ainda.
