# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral

Auditoria dos balancetes mensais (PDF) de um clube social e esportivo: extrai os extratos bancários
Santander e o Balancete Analítico contábil, confere tudo contra os saldos impressos, grava no PostgreSQL
e expõe um site (FastAPI) com painel, transações, eventos, pontos de atenção e um chat NL→SQL com LLM local.
Tudo roda localmente; os dados do clube são sensíveis (pastas `balancetes pcsf/`, `dados/`, `saidas/` e `.env`
estão no `.gitignore` e não devem ser versionados nem enviados para fora da máquina).

Os dados que identificam o clube (nome, CNPJ, contas Santander/Sicredi, mapa conta contábil → conta bancária) vêm do
`.env` via `pcsf/clube.py`. Nunca os escreva no código, nos SQL de `db/init/`, nos testes ou na documentação:
o repositório deve poder ser publicado como portfólio. O mesmo vale para valores financeiros reais e nomes de fornecedores.
O plano de contas acompanhado (`balancete_filtros`) fica em `db/init/900_contas_local.sql` e os nomes reais das
contas citadas no benchmark em `avaliacao/apelidos.json` (nome fictício → real); os dois estão no `.gitignore`.

## Comandos

Windows, a partir da raiz do projeto, sempre com o Python do `.venv`:

```bash
docker compose up -d                                          # PostgreSQL 16 + pgvector na porta 5433
.venv/Scripts/python -m pcsf.carga "balancetes pcsf"          # carrega PDFs novos (ignora os já carregados pelo SHA-256)
.venv/Scripts/python -m pcsf.carga "balancetes pcsf" --recarregar   # TRUNCATE + recarga completa
.venv/Scripts/python -m pcsf.balancete                        # (re)carrega só o balancete contábil
.venv/Scripts/python -m pcsf.relatorios todos                 # gera os Excel em saidas/
.venv/Scripts/python -m pcsf.sugerir                          # LLM sugere categoria por recebedor
.venv/Scripts/python -m pcsf.revisao exportar|importar        # ciclo de revisão de categorias via Excel
.venv/Scripts/python -m uvicorn web.app:app --port 8500       # site em http://127.0.0.1:8500
```

`iniciar_site.bat` faz banco + site + navegador (porta 8500, ou 8501 se ocupada).

Testes (pytest, instalado via `requirements-dev.txt`; não precisam do banco nem do LLM):

```bash
.venv/Scripts/python -m pytest                                   # todos
.venv/Scripts/python -m pytest tests/test_chat.py::test_sql_seguro_bloqueia   # um só
```

Os testes cobrem as funções puras (valores, tipos, contrapartes, OCR, conciliação, travas do chat) com dados fictícios;
nunca use nomes, CPFs ou valores reais do clube neles. A validação da extração real continua sendo a conferência
contra o banco (tabela `conciliacoes`, impressa no log da carga). Não há linter configurado.

Benchmark do chat NL→SQL (precisa do banco e dos servidores de LLM):

```bash
.venv/Scripts/python -m avaliacao.benchmark --validar                       # confere os SQL de referência
.venv/Scripts/python -m avaliacao.benchmark chat-8b chat-moe-30b "ollama/qwen2.5:7b" [--repeticoes N] [--so mov-01]
```

`avaliacao/perguntas.json` tem perguntas com SQL de referência; o benchmark gera o SQL por `web.app.gerar_sql`
(o mesmo caminho do chat) e usa `confere` para comparar resultados. Resumo sem valores em `avaliacao/RESULTADOS.md`;
detalhe com valores reais em `saidas/` (fora do Git). Ao mudar o prompt do chat, rode o benchmark antes e depois.

Novos PDFs: `balancetes pcsf/Balancete AAAA-MM-MES.pdf` (a competência é lida do nome do arquivo).

## Arquitetura

**Pipeline de carga (`pcsf/carga.py`)**, em uma única transação:
1. `extratos.extrair` lê os extratos pela **posição das palavras** no PDF (pymupdf), com dois layouts
   (`_pagina_a` / `_pagina_b`). Páginas sem texto (ex.: jul/2025, desenhado como vetor) vão para `ocr.pagina_ocr`
   (RapidOCR, cache em `dados/cache_ocr`); o texto do OCR é corrigido com o `Vocabulario` montado a partir
   das descrições dos meses com texto. Por isso todos os arquivos são extraídos antes de gravar.
2. `conciliacao` confere saldo corrido (saldo anterior + lançamentos = saldo impresso) e resumo mensal;
   o resultado vai para `conciliacoes` e define `documentos.status` (`carregado` / `revisar`).
3. `classificar` define tipo, flag `interna` (transferências entre contas do clube, incl. Sicredi, conforme `pcsf/clube.py`)
   e contraparte.
4. `balancete.gravar` extrai o Balancete Analítico (colunas por coordenada X, códigos `[123]`, linhas `=` de total)
   para a tabela `balancete`, com conferência de partidas dobradas.
5. `deduplicar` marca `duplicada_de` em linhas repetidas entre impressões diferentes do extrato
   (regra no docstring: vale o maior número de ocorrências numa mesma impressão).
6. `categorizar` aplica a precedência: categoria revisada do recebedor (`contrapartes.categoria_id`)
   > regex de `regras_categoria` > tipo do lançamento. Marcações `manual` sem recebedor não são tocadas.

Para análises use a visão **`v_movimentos`** (exclui duplicatas e movimentos internos), não `transacoes` direto.
Contabilidade × extrato são extrações independentes: `v_balancete_selecionado` (contas listadas em
`balancete_filtros`, casadas pelo **código**, pois nomes se repetem) e `movimentos_financeiros` (8 “strings” sobre `transacoes`).

**Site (`web/app.py` + `web/static/`)**: FastAPI em um único arquivo, SQL escrito à mão, front-end em JS puro.
CPFs são mascarados em `jsonavel`/`mascara` (LGPD) antes de qualquer resposta; mantenha isso em endpoints novos.

**Chat NL→SQL (`/api/chat`)**: a geração fica em `gerar_sql()` (também usada pelo benchmark). Antes do LLM,
`dicas_esquema()` faz *schema linking*: acha na pergunta nomes de contas do balancete e de categorias e acrescenta
dicas determinísticas (foi o que mais elevou o acerto do 8B; veja `avaliacao/RESULTADOS.md`). `system_sql()` monta o prompt com o esquema (`ESQUEMA`) e os nomes exatos das contas
de `balancete_filtros` → `pcsf.llm.chat_json` gera o SQL → `_sql_seguro` aceita só um `SELECT`/`WITH`, sem palavras
proibidas, e força `LIMIT 500` → executa como o usuário **`leitor`** (somente leitura, `statement_timeout` 15s) com
uma tentativa de correção em caso de erro → o LLM redige a resposta e `numeros_conferem` descarta a frase se citar
número que não está no resultado. Tudo é registrado em `consultas_log`. Novas tabelas/visões que o chat deva
consultar precisam de `GRANT SELECT ... TO leitor` e de menção em `ESQUEMA`.

**LLM (`pcsf/llm.py`)**: cliente mínimo para API compatível com OpenAI (`/v1/chat/completions`, resposta em JSON,
thinking desligado para Qwen3). Configurado por `LLM_URL` / `LLM_MODEL` no `.env` (llama-swap em `:8080` com
`chat-8b`, ou Ollama em `:11434` com `qwen2.5:7b`). Os prompts são pensados para modelos de ~8B.

## Banco de dados

- Conexão em `pcsf/db.py` a partir do `.env` (`DATABASE_URL` ou `POSTGRES_*`; porta 5433 porque a 5432 é de outro projeto).
- Esquema em `db/init/*.sql`, numerados. O Postgres só executa essa pasta quando o volume `pgdata` está vazio:
  um script novo precisa ser aplicado à mão no banco existente, por exemplo
  `docker compose exec -T db psql -U auditoria -d auditoria < db/init/008_xxx.sql`.
  Escreva scripts idempotentes (`CREATE OR REPLACE VIEW`, `IF NOT EXISTS`) e acrescente um arquivo novo em vez de editar os antigos.
- A senha do papel `leitor` vem de `LEITOR_PASSWORD` no `.env`, mas nenhum script do repositório a define:
  num banco novo é preciso rodar `ALTER ROLE leitor PASSWORD '...'`.

## Limites conhecidos dos dados

- PIX enviado traz só o nome do recebedor (cortado em 25 caracteres), sem CPF/CNPJ; PAGFOR não mostra o recebedor.
- PIX recebido traz o CPF do pagador (sócios): dado pessoal, sempre mascarar.
- Contas do Sicredi (desde jan/2026) não têm extrato nos balancetes; a partir de mai/2026 as mensalidades saem do
  Santander, então comparações 2025 × 2026 ficam incompletas.
