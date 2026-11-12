# Instruções do projeto

## Objetivo

Este projeto constrói e mantém um site com várias páginas e um banco de dados pequeno para armazenar as informações necessárias ao funcionamento do produto. Atue como responsável por implementar, revisar e aprimorar todas as páginas e os fluxos relacionados, mantendo consistência entre interface, lógica e dados.

## Antes de alterar

- Leia o código e a documentação existentes para identificar o framework, a estrutura, os comandos disponíveis e os padrões já adotados.
- Verifique as instruções em `AGENTS.md` mais específicos nas pastas que pretende alterar.
- Preserve as escolhas e convenções do projeto. Não introduza outra stack, dependências ou serviços sem necessidade concreta.
- Se o repositório ainda estiver vazio ou faltar contexto essencial, prepare uma base simples e coerente com o pedido e registre claramente as decisões tomadas.

## Desenvolvimento do site

- Pense no conjunto completo de páginas: navegação, estados vazios, carregamento, erros, validação e confirmação das ações.
- Mantenha layout, componentes, tipografia, cores e comportamento consistentes. Prefira componentes reutilizáveis quando reduzirem duplicação sem esconder a lógica.
- Faça páginas responsivas e acessíveis: HTML semântico, navegação por teclado, rótulos para campos, foco visível, contraste adequado e mensagens de erro compreensíveis.
- Apresente conteúdo e ações em português, salvo quando o projeto ou o pedido estabelecer outro idioma.
- Evite conteúdo fictício em produção e controles que pareçam funcionais sem realmente executar a ação indicada.

## Banco de dados e segurança

- Mantenha a solução de persistência proporcional ao volume e às necessidades do projeto; evite infraestrutura complexa para um conjunto pequeno de dados.
- Defina e preserve um esquema claro, com tipos, identificadores, restrições e relações necessários. Use migrações ou outro mecanismo versionado já adotado pelo projeto.
- Valide dados no servidor mesmo quando também houver validação no navegador. Trate campos ausentes, inválidos, duplicados e registros inexistentes.
- Use consultas parametrizadas ou o mecanismo seguro do ORM. Nunca concatene entrada do usuário em consultas.
- Não exponha segredos, credenciais, dados pessoais ou detalhes internos em código do cliente, logs ou mensagens de erro. Use variáveis de ambiente e mantenha exemplos sem credenciais reais.
- Aplique permissões e proteção contra operações não autorizadas conforme os recursos existentes; colete e armazene somente os dados necessários.

## Qualidade e manutenção

- Faça mudanças focadas, legíveis e consistentes com o estilo existente; atualize a documentação quando comportamento, configuração ou dados mudarem.
- Considere os efeitos de cada alteração nas páginas, na navegação, nas APIs e no esquema de dados.
- Não remova dados nem faça alterações destrutivas no banco sem instrução explícita.
- Ao revisar código, procure bugs, falhas de segurança, problemas de acessibilidade, inconsistências visuais e comportamento incorreto; explique achados com arquivo e localização.
- Ao concluir uma alteração, resuma o que mudou e informe limitações ou verificações realizadas. Execute verificações disponíveis quando solicitado ou quando forem necessárias para confirmar o resultado.
