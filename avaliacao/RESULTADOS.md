# Benchmark do chat NL→SQL

Perguntas em português → SQL gerado por LLM local → resultado comparado com um SQL de referência escrito à mão
(`avaliacao/perguntas.json`). Detalhe de cada rodada (com valores reais) fica em `saidas/`, fora do Git.

## Evolução do Qwen3-8B (`chat-8b`, Q4_K_M, RTX 3050 6 GB)

| Versão | O que mudou | Ajuste (27) | Validação (8) | Validação 2 (8) | Total | Respostas vazias | Tempo médio |
|---|---|---|---|---|---|---|---|
| v1 | Prompt original | 67% | 25% | — | 57% (35) | 7 | 9,7–11,3 s |
| v2 | Regras novas no prompt: total × mês a mês, comparação de períodos com `FILTER` (sem `UNION`), `tipo = 'conta'`, direção de pagamentos, lista completa de categorias | 78% | 62% | — | 74% (35) | 7 | 9,8 s |
| v3 | + **schema linking**: o código identifica na pergunta contas do balancete e categorias que existem e passa ao modelo dicas determinísticas (`dicas_esquema` em `web/app.py`) | 93% | 88% | 88% | 91% (35) | 0 | 9,4 s |
| v4 | + dica determinística de **total × mês a mês**: se a pergunta não pede valores por mês, o modelo é instruído a somar o período inteiro | **96%** | **100%** | **100%** | **98% (43)** | 0 | 8,9 s |

- *Ajuste*: perguntas cujos erros orientaram as mudanças. *Validação*: 8 perguntas novas, escritas depois da v1 e
  medidas antes de qualquer mudança (linha de base de 25%). *Validação 2*: mais 8 perguntas novas, escritas depois
  da v3 e medidas com a v3 antes de criar a v4 (linha de base de 88%).
- O ganho maior veio do schema linking, não do prompt: o 8B não consulta de forma confiável listas longas dentro do
  prompt (procurava a conta "Natação" como categoria dos extratos), mas segue bem uma dica curta e específica.

### Ressalvas

- Amostra pequena (43 perguntas) e 1 repetição por versão: diferenças de 1 ou 2 perguntas estão dentro do ruído.
- Os erros da validação na v2 foram examinados antes de criar a v3, então os 88% da v3 nela são um pouco otimistas.
  A validação 2 corrige isso para a v3/v4. Para a próxima rodada de ajustes, crie de novo perguntas novas de validação.
- Entre a v1 e a v2 a referência da `mov-10` foi corrigida (contava 2 estornos como pagamentos; o modelo estava certo).

### Erros que restam na v4

- "Recebedores com nome identificado": o modelo não exclui os lançamentos sem nome.

## Comparação de modelos

Com o pipeline v4 (43 perguntas):

| Modelo | Acerto | Ajuste | Validação | Validação 2 | Tempo médio | Memória |
|---|---|---|---|---|---|---|
| Qwen3-8B (`chat-8b`) | **98%** | 96% | 100% | 100% | 8,9 s | ~5 GB (quase todo na GPU) |
| Qwen3-30B-A3B (`chat-moe-30b`, MoE com 3B ativos) | 95% | 93% | 100% | 100% | 10,3 s | ~18 GB de RAM + GPU |

- A dica de total × mês resolveu o principal erro do 30B (de 83% para 95%). Os 2 erros dele: a mesma `mov-04` do 8B
  e o JOIN entre texto e data em `documentos`, que falhou mesmo após a correção automática.
- Na prática os dois empatam; o 8B fica como padrão por ser mais rápido e caber quase todo na GPU de 6 GB.

Com o pipeline v3 (35 perguntas):

| Modelo | Acerto | Ajuste | Validação | Tempo médio | Memória |
|---|---|---|---|---|---|
| Qwen3-8B (`chat-8b`) | **91%** | 93% | 88% | 9,4 s | ~5 GB (quase todo na GPU) |
| Qwen3-30B-A3B (`chat-moe-30b`, MoE com 3B ativos) | 83% | 89% | 62% | 10,9 s | ~18 GB de RAM + GPU |

- O 30B não teve nenhuma resposta vazia, mas em 4 dos 6 erros devolveu mês a mês quando a pergunta pedia o total
  (mesmo erro que resta no 8B, só que mais frequente). Também errou um JOIN entre texto e data (`documentos`).
- O prompt e as dicas da v3 foram ajustados olhando os erros do 8B; parte da vantagem do 8B pode vir disso.

Com o prompt v1 (27 perguntas):

| Modelo | Acerto | Tempo médio |
|---|---|---|
| Qwen3-8B (`chat-8b`, llama-swap) | **67%** | 9,7 s |
| Qwen2.5-7B (`qwen2.5:7b`, Ollama) | 37% | 6,2 s |

## Última rodada (v4) por fonte de dados

| Modelo | balancete | documentos | movimentos | movimentos_financeiros |
|---|---|---|---|---|
| chat-8b | 100% | 100% | 95% | 100% |
| chat-moe-30b | 100% | 0% (1 pergunta) | 95% | 100% |

Critério: o resultado do modelo precisa conter todos os números (e nomes) do resultado de referência, sem linhas
demais. Status: *vazio* = SQL válido sem linhas; *erro SQL* = falhou mesmo após a correção automática;
*bloqueado* = barrado pela trava de segurança.
