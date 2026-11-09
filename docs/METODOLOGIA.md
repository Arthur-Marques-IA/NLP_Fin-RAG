# Metodologia — Representação de Tabelas em QA Financeiro (FinQA)

Este documento é a referência de **como o estudo será conduzido**. Ele fixa o que comparamos, o que mantemos constante, como medimos e como decidimos se uma diferença é real. Toda escolha de implementação no notebook deve seguir este texto; quando o código e este documento divergirem, o documento vale e o código deve ser corrigido.

---

## 1. Pergunta e hipóteses

**Pergunta.** Em perguntas numéricas sobre relatórios financeiros, como a forma de apresentar a tabela ao LLM afeta a acurácia e o custo em tokens, e como esse efeito muda com a complexidade do raciocínio?

| Hipótese | Enunciado | Contraste que a testa |
|---|---|---|
| **H1** | O formato da tabela altera a acurácia de modelos abertos pequenos, e o melhor formato pode variar entre modelos. | R1 × R2 × R3 (e R0 como controle), tabela completa |
| **H2** | Selecionar linhas reduz tokens sem perder acurácia quando a seleção preserva os operandos, e perde quando os corta. | R4 × R1, no subconjunto em que a seleção corta linhas; R5 × R1 como teto |
| **H3** | As diferenças entre representações crescem nas perguntas de mais passos e nas que exigem tabela e texto. | Interação representação × passos e representação × origem da evidência |

**Variável independente:** só a representação da tabela.
**Variáveis dependentes:** acurácia, tokens de entrada, tokens de saída, taxa de falha de formato.

---

## 2. As representações comparadas

Todas partem da mesma `table` do FinQA: lista de linhas, em que a linha 0 é o cabeçalho e a coluna 0 é o rótulo da linha. **Os valores das células não são alterados** em nenhuma representação (ex.: `$ 5735` e `-32 ( 32 )` aparecem exatamente assim). Só muda a forma.

### 2.1 Visão geral

| Código | Nome | Conteúdo | Formato | Papel no estudo |
|---|---|---|---|---|
| **R0** | Bruta | tabela completa | células separadas por espaço, uma linha por linha da tabela, sem marcação de coluna | **controle**: como a tabela sai de um extrator de PDF |
| **R1** | Markdown | tabela completa | tabela Markdown com cabeçalho | **referência** de todos os contrastes |
| **R2** | JSON | tabela completa | lista de objetos, um por linha, chaves = cabeçalhos | formato estruturado (Singha et al.; base do TOON/JTON) |
| **R3** | Linearizada | tabela completa | uma frase por célula: `the <linha> of <coluna> is <valor> ;` | template do próprio FinQA / serialização por célula do MT2Net |
| **R4** | Seletiva | cabeçalho + *k* linhas mais relevantes à pergunta | **Markdown** (igual a R1) | testa a seleção (H2) |
| **R5** | Gold-tabela | cabeçalho + linhas do gabarito | **Markdown** (igual a R1) | **diagnóstico**: teto da seleção; não concorre |

Por que essa grade isola as variáveis:
- **R0, R1, R2 e R3 têm o mesmo conteúdo** e só diferem na forma → a diferença entre elas é efeito de **formato** (H1).
- **R1, R4 e R5 têm o mesmo formato** e só diferem nas linhas incluídas → a diferença entre elas é efeito de **seleção** (H2).
- R0 responde se *qualquer* estrutura ajuda; sem ele, não dá para dizer se o Markdown é bom ou só "não atrapalha".

### 2.2 Exemplo — a mesma tabela nas seis representações

Pergunta `ETR/2016/page_23.pdf-2`: *"what is the net change in net revenue during 2015 for entergy corporation?"* — programa `subtract(5829, 5735)`, resposta 94. Linhas do gabarito: 1 e 8.

**R0 — Bruta**
```
amount ( in millions )
2014 net revenue $ 5735
retail electric price 187
volume/weather 95
waterford 3 replacement steam generator provision -32 ( 32 )
miso deferral -35 ( 35 )
louisiana business combination customer credits -107 ( 107 )
other -14 ( 14 )
2015 net revenue $ 5829
```

**R1 — Markdown**
```
| item | amount ( in millions ) |
|---|---|
| 2014 net revenue | $ 5735 |
| retail electric price | 187 |
| ... (todas as 8 linhas) ... |
| 2015 net revenue | $ 5829 |
```

**R2 — JSON**
```json
[{"item": "2014 net revenue", "amount ( in millions )": "$ 5735"},
 {"item": "retail electric price", "amount ( in millions )": "187"},
 ...,
 {"item": "2015 net revenue", "amount ( in millions )": "$ 5829"}]
```

**R3 — Linearizada**
```
the 2014 net revenue of amount ( in millions ) is $ 5735 ;
the retail electric price of amount ( in millions ) is 187 ;
...
the 2015 net revenue of amount ( in millions ) is $ 5829 ;
```

**R4 — Seletiva (k = 4, escolhido no dev)**
```
| item | amount ( in millions ) |
|---|---|
| 2014 net revenue | $ 5735 |
| retail electric price | 187 |
| volume/weather | 95 |
| 2015 net revenue | $ 5829 |
```

**R5 — Gold-tabela**
```
| item | amount ( in millions ) |
|---|---|
| 2014 net revenue | $ 5735 |
| 2015 net revenue | $ 5829 |
```

### 2.3 Regras de cada representação

**Cabeçalho.** Em R1, R2, R4 e R5, a primeira coluna do cabeçalho costuma vir vazia no FinQA; ela recebe o nome `item` (e colunas repetidas recebem sufixo `_1`, `_2`) para que o Markdown tenha cabeçalho e o JSON tenha chaves únicas. É a única palavra adicionada, e é igual nas quatro. R0 e R3 usam o cabeçalho original.

**Células vazias.** R0 e R3 omitem células vazias (não há o que dizer); R1 e R2 as mantêm como `""`, porque fazem parte da grade.

**R3 — Template do FinQA, reproduzido à risca.** Cada célula vira `the <rótulo da linha> of <nome da coluna> is <valor> ;`. Quando a primeira célula do cabeçalho não é vazia (ex.: `december 31,`), ela prefixa a primeira frase de cada linha, como no FinQA; coluna sem nome gera `the <linha> of is <valor> ;`, também como no FinQA. Linhas só com rótulo (títulos de seção) viram `<rótulo> ;`, para não perder conteúdo. A verificação V1b confere que as frases geradas batem com as frases de `gold_inds` do próprio dataset em 99,7% das linhas do gabarito (2.364 de 2.372); o resto difere só no espaçamento de pontuação, porque o FinQA tokeniza o cabeçalho e nós não alteramos as células.

**Tabelas de uma linha só.** Em 4 perguntas do teste (um mesmo documento), a tabela inteira está na linha 0. Ela é tratada como uma linha de dados com cabeçalho vazio; sem isso, R2 e R3 sairiam vazias e perderiam todo o conteúdo.

**R4 — Seleção de linhas.**
- Pontuação de cada linha = soma dos termos que ela compartilha com a pergunta, após minúsculas e remoção de stopwords; números e anos valem 2, palavras valem 1.
- Mantém as *k* linhas de maior pontuação, **na ordem original** da tabela. Empates: a linha que vem antes. Pontuação toda zero: as *k* primeiras linhas.
- Usa **só a pergunta e a tabela**. Não usa gabarito, programa, `gold_inds` nem os campos de recuperação do FinQA (`table_retrieved*`, `text_retrieved*`, `tfidftopn`, `model_input`).
- Não usa LLM; o custo da seleção é zero em tokens de modelo.
- **k é escolhido no dev** (seção 4) e congelado antes de rodar o teste.

**R5 — Gabarito de linhas.** As linhas vêm das chaves `table_i` de `gold_inds`. O campo `ann_table_rows` **não** é usado porque vem vazio em ~110 perguntas do teste que têm linhas no gabarito. R5 fornece só as linhas da tabela; **não** fornece os fatos do texto. Logo, é o teto da *seleção de tabela*, e não equivale ao "FinQANet-Gold" do artigo original.

### 2.4 O que é igual em todas as condições

O contexto é sempre montado assim, e só o bloco `<TABELA>` muda:

```
<pre_text unido por espaço>

Table:
<TABELA na representação da condição>

<post_text unido por espaço>
```

---

## 3. Controles experimentais

Tudo abaixo é **idêntico entre as seis condições**, para que a representação seja a única variável.

| Item | Decisão |
|---|---|
| **Texto do relatório** | `pre_text` e `post_text` sem alteração, mesma posição em todas as condições |
| **Instrução** | um único template em inglês (os dados são em inglês), com a pergunta **depois** do contexto |
| **Few-shot** | 3 exemplos fixos do **treino** do FinQA (um de 1 passo com tabela, um de 2 passos com tabela + texto, um com evidência só no texto), escolhidos uma vez com semente fixa. **As tabelas dos exemplos são serializadas na mesma representação da condição** — senão o modelo vê Markdown nos exemplos e JSON na pergunta |
| **Formato da saída** | raciocínio curto e última linha `Answer: <número>`, com 2 casas decimais, na unidade da tabela, porcentagens com `%`; sim/não como `Answer: yes` ou `Answer: no` |
| **Decodificação** | gulosa (temperatura 0), mesmo `max_new_tokens` para todos (512) |
| **Chat template** | o template oficial de cada modelo, com `add_generation_prompt=True` |
| **Modo de raciocínio** | Qwen3 com `enable_thinking=False`, para que os três modelos gerem no mesmo regime e o custo de saída seja comparável |
| **Precisão numérica** | **a mesma para os três modelos.** Preferência: bf16 em GPU L4/A100. Na T4 (15 GB): 4 bits NF4 para **todos**, inclusive o Phi-4-mini. Misturar 4 bits nos de 8B com fp16 no Phi confundiria a comparação entre modelos |
| **Versões** | revisão (commit hash) de cada modelo no Hugging Face, versões de `transformers`/`torch`/`bitsandbytes` registradas no início da execução |

Template de prompt (a ser congelado após o piloto no dev):

```
You are a financial analyst. Answer the question using the report below.
Think step by step briefly, then give the final answer on the last line as
"Answer: <number>" with two decimals, in the same unit as the table
(use % for percentages). For yes/no questions, write "Answer: yes" or "Answer: no".

<exemplo 1: contexto + pergunta + resposta>
<exemplo 2>
<exemplo 3>

Report:
<contexto da condição>

Question: <pergunta>
```

---

## 4. Uso dos splits do FinQA

Para que nenhuma decisão seja ajustada olhando o resultado do teste:

| Split | Tamanho | Uso |
|---|---|---|
| **train** | 6.251 | apenas para sortear os 3 exemplos few-shot |
| **dev** | 883 | escolher *k* da seletiva; piloto (≈150 perguntas) para validar o prompt, o parser e a taxa de falha de formato |
| **test** | 1.147 | **execução final, uma vez**, com tudo congelado |

**Critério para k (fixado antes de olhar o dev):** entre *k* ∈ {1, …, 5}, o menor *k* em que a seletiva preserva **todas** as linhas do gabarito em ≥ 80% das perguntas do dev com linhas de dados no gabarito; se nenhum atingir, *k* = 5.

**Resultado no dev (683 perguntas com linhas no gabarito):**

| k | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| todas as linhas gold preservadas | 42,8% | 66,2% | 77,5% | **84,2%** | 89,9% |

**→ k = 4**, congelado para o teste.

> Nota de transparência: uma versão anterior do notebook calculou o recall da seleção para vários *k* no teste, como exploração. A escolha final foi feita no dev pela regra acima, e o relatório deve mencionar a exploração anterior.

---

## 5. Modelos

| Modelo | Repositório | Parâmetros | Observação |
|---|---|---|---|
| Llama 3.1 8B Instruct | `meta-llama/Llama-3.1-8B-Instruct` | 8,0B | *gated*: precisa de `HF_TOKEN` com acesso |
| Qwen3-8B | `Qwen/Qwen3-8B` | 8,2B | `enable_thinking=False` |
| Phi-4-mini-instruct | `microsoft/Phi-4-mini-instruct` | 3,8B | porte menor: permite ver o efeito do tamanho |

São dois portes (≈8B e ≈4B), não três modelos de ~8B. O texto do trabalho deve dizer "modelos abertos de 4B a 8B".

---

## 6. Medidas

### 6.1 Acurácia (métrica principal)

Gabarito: `exe_ans`, o resultado da execução do programa anotado (como a acurácia de execução do FinQA). O campo `answer`, escrito à mão, tem ruído e não é usado como gabarito.

**Extração da resposta:** lê-se **somente o texto após o último `Answer:`**. Se não houver `Answer:` ou número legível ali, a saída conta como **falha de formato** (e como erro na acurácia).

**Acurácia estrita (principal)** — correta se o erro relativo for ≤ 1% em uma destas escalas:
- `pred` ≈ `gold`;
- `pred` ≈ `gold × 100` (porcentagem escrita como número: `14.46` ou `14.46%` para `0.1446`).

A escala `pred ≈ gold ÷ 100` **não** é aceita: ela casaria uma razão com um valor em milhões.

**Acurácia tolerante (sensibilidade)** — a estrita **ou** a tolerância de arredondamento: o gabarito, arredondado com as casas decimais que a resposta usou, é igual à resposta, com o mesmo sinal, resposta ≠ 0 **e erro relativo ≤ 5%**. O teto de 5% impede que uma resposta pouco precisa ganhe tolerância grande (sem ele, `Answer: 1` seria aceito para 1,4).

**Sim/não** (20 perguntas): comparação exata após `Answer:`.

**Por que duas métricas:** a conclusão do estudo deve valer nas duas. Se uma diferença entre representações só aparece na tolerante, ela é tratada como frágil.

Casos que o parser precisa acertar (testes unitários do notebook):

| Saída do modelo | Gabarito | Estrita | Tolerante |
|---|---|---|---|
| `Answer: 94.00` | 94.0 | ✓ | ✓ |
| `Answer: 14.46%` | 0.14464 | ✓ | ✓ |
| `Answer: 14%` | 0.14464 | ✗ | ✓ |
| `Answer: (32.00)` | −32.0 | ✓ | ✓ |
| `Answer: 1` | 1.4 | ✗ | ✗ |
| `Answer: 0.94` | 94.0 | ✗ | ✗ |
| `There was no change. Answer: yes` | yes | ✓ | ✓ |
| `The answer is 94` (sem `Answer:`) | 94.0 | ✗ (falha de formato) | ✗ |

### 6.2 Custo

Contados com o **tokenizador de cada modelo**, já com o chat template aplicado:
- **tokens do contexto da pergunta** (relatório + tabela) — isola o custo da representação;
- **tokens totais de entrada** (instrução + few-shot + contexto) — custo real da chamada;
- **tokens de saída** gerados — a representação pode mudar o tamanho do raciocínio.

O custo da seleção (R4) é zero em tokens de LLM e é declarado como tal.

### 6.3 Falha de formato

Fração de saídas sem `Answer:` legível, por modelo × representação. Uma representação que confunde o modelo a ponto de ele não seguir o formato é um resultado em si, e precisa ser separada de erro de conteúdo.

### 6.4 Tipo de erro (extração × cálculo)

Para cada resposta errada com formato válido:
- **erro de extração** — algum operando numérico do programa do gabarito (números do `program`, sem referências `#n` e constantes `const_*`) **não aparece** no raciocínio do modelo;
- **erro de cálculo** — todos os operandos aparecem, mas a resposta final está errada.

É uma heurística automática; uma amostra de 50 erros por modelo é conferida à mão para estimar sua precisão.

---

## 7. Análise

### 7.1 Contrastes pré-definidos

Todos são **pareados** (mesmas perguntas, mesmo modelo) e têm R1 (Markdown completo) como referência:

| Contraste | Hipótese | Conjunto de perguntas |
|---|---|---|
| R0 − R1 | H1 (estrutura importa?) | todas |
| R2 − R1 | H1 | todas |
| R3 − R1 | H1 | todas |
| R4 − R1 | H2 | **subconjunto efetivo**: tabela com mais de *k* linhas de dados e com linhas no gabarito |
| R5 − R1 | H2 (teto) | mesmo subconjunto efetivo |

São 5 contrastes × 3 modelos = 15 testes.

**Por que o subconjunto efetivo para H2:** com *k* = 4, R4 é idêntica a R1 em 493 perguntas (43%, tabelas com até 4 linhas de dados), e em perguntas sem linhas no gabarito não há o que preservar. Incluí-las diluiria o efeito da seleção. O **subconjunto efetivo tem 488 perguntas**: tabela com mais de 4 linhas de dados e com linhas no gabarito. Também se reporta R4 − R1 em todas as perguntas, como efeito prático.

**H2 em duas partes:** dentro do subconjunto efetivo, R4 − R1 é estimado separadamente onde a seleção **preservou** todas as linhas do gabarito (348 perguntas, 71,3%) e onde **cortou** alguma (140). H2 prevê ≈ 0 no primeiro grupo e < 0 no segundo. Essa divisão depende da pergunta (perguntas com vocabulário parecido com a tabela tendem a ser mais fáceis), então é descritiva, não causal.

### 7.2 Estatística

- Diferença de acurácia com **IC de 95% por bootstrap pareado** (10.000 reamostragens de perguntas).
- **Teste de McNemar exato** para cada contraste.
- **Correção de Holm** sobre os 15 testes.
- Tamanho de efeito reportado em pontos percentuais, sempre com o IC.

### 7.3 Cortes (H3)

| Corte | Níveis | n no teste |
|---|---|---|
| Passos do programa | 1 / **2+** (principal); 3+ exploratório | 654 / 493 (dos quais 84 com 3+) |
| Origem da evidência | tabela / texto / ambos | 706 / 283 / 158 |
| Tamanho da tabela | até 4 linhas / mais de 4 linhas | 493 / 654 |

O corte 3+ tem só 84 perguntas (IC de cerca de ±10 pontos) e é tratado como exploratório; a H3 é testada com 1 × 2+.

**Verificação de sanidade (placebo):** nas perguntas com evidência **só no texto**, a tabela não contém a resposta. Se a representação muda muito a acurácia nesse grupo, o efeito vem de distração ou do tamanho do prompt, não da leitura da tabela — e isso precisa ser discutido.

### 7.4 Custo × acurácia

- **Fronteira de Pareto** (acurácia × tokens totais de entrada) por modelo: uma representação é preferível quando nenhuma outra tem mais acurácia com menos tokens.
- **Δacurácia / Δtokens** em relação a R1, com IC.
- "Acurácia por mil tokens" (como no TOON) é reportada só para comparação com a literatura, porque favorece contextos curtos por construção.

---

## 8. Verificações obrigatórias antes de rodar o teste

Estas verificações garantem que os métodos comparados são o que dizemos que são. Cada uma vira uma célula com `assert` no notebook.

| # | Verificação | Onde | Resultado atual (dev + teste, 2.030 tabelas) |
|---|---|---|---|
| V1 | **Mesmo conteúdo em R0–R3:** todo valor de célula, rótulo de linha, nome de coluna com dados e cabeçalho da coluna 0 aparece nas quatro; nenhuma sai vazia | notebook 01 | 0 falhas |
| V1b | **R3 reproduz o template do FinQA:** frases geradas = frases de `gold_inds` (ignorando espaços) | notebook 01 | 99,7% (mínimo exigido: 99%) |
| V2 | **Mesmo formato em R1, R4, R5:** R4 e R5 têm o cabeçalho de R1 e suas linhas são subsequência das de R1 | notebook 01 | 0 falhas |
| V3 | **Sem vazamento na seleção:** `select_rows` recebe só `(table, question, k)`, e a seletiva não muda quando o gabarito é removido do exemplo | notebook 01 | 0 falhas |
| V4 | **Texto fixo:** fora do bloco da tabela, o contexto é idêntico nas seis condições | notebook 01 | 0 falhas |
| V5 | **Few-shot coerente:** os exemplos de cada condição usam a representação da condição; os IDs dos exemplos não estão no teste nem no dev | notebook 02 | a implementar |
| V6 | **Parser:** todos os casos da tabela 6.1 (e extras) passam | notebook 01 | 19 casos OK |
| V7 | **Piloto no dev:** falha de formato < 5% em cada modelo com R1; se passar disso, o prompt é ajustado **no dev** e congelado | notebook 02 | a implementar |

As verificações já pegaram três defeitos que mudariam os resultados: a ordem invertida do template da R3, a perda total de conteúdo de R2/R3 em tabelas de uma linha só, e o colapso de espaços dentro de valores de célula.

---

## 9. Execução e registro

- Total: 1.147 perguntas × 6 condições × 3 modelos = **20.646 gerações**.
- Resultados salvos em JSONL no Google Drive, um arquivo por modelo × condição, com retomada automática: se a sessão do Colab cair, as perguntas já feitas não são repetidas.
- Campos de cada registro: `id`, `model`, `rep`, `k`, `prompt_tokens`, `context_tokens`, `output_tokens`, `raw_output`, `parsed_answer`, `format_ok`, `correct_strict`, `correct_lenient`, `error_type`, `latency_s`.
- Metadados da execução: GPU, versões das bibliotecas, revisão de cada modelo, semente dos few-shot, *k* escolhido, hash do template de prompt.

---

## 10. Escopo e limitações declaradas

- Sem ajuste fino (alternativa do TAT-LLM) e sem agentes com acesso por código (alternativa do TableRAG).
- Tabelas do FinQA são pequenas e regulares (média de 5,5 linhas de dados); a conclusão não se estende a tabelas hierárquicas (MultiHiertt) nem a tabelas grandes, onde a economia da seleção seria maior.
- A tabela ocupa uma fração pequena do contexto (~150–190 de ~890–1.000 tokens no Markdown), então diferenças de custo entre representações tendem a ser modestas — isso é um achado, não uma falha. Contexto médio relativo a R1, no teste: R0 0,96×, R2 1,13×, R3 1,18×, R4 0,95× (0,90× no subconjunto efetivo), R5 0,88× (Qwen3 e Phi-4-mini; Llama pendente de `HF_TOKEN`).
- Se a execução for em 4 bits, os resultados absolutos ficam abaixo dos de bf16; a comparação **entre representações dentro do mesmo modelo** continua válida.
- A heurística de tipo de erro é aproximada e validada por amostra.

---

## 11. Decisões tomadas e alternativas descartadas

| Decisão | Alternativa | Motivo |
|---|---|---|
| Linearizada = frase por célula (R3) **e** bruta como controle (R0) | só uma delas | A proposta original chamava a linearizada de controle; o related work a descreve como frase por célula, que é uma representação forte. Separar as duas resolve a ambiguidade |
| Seletiva em Markdown | seletiva em JSON | Isola a seleção do formato (R4 × R1 só difere nas linhas) |
| Seleção lexical | seleção por embeddings ou por LLM | Sem custo de tokens e sem vazamento; seleção por LLM misturaria custo e qualidade do seletor |
| `gold_inds` para R5 | `ann_table_rows` | `ann_table_rows` vem vazio em ~110 perguntas com gabarito |
| Resposta em texto + heurística de erro | modelo gera programa executável | Mantém o cenário próximo do uso real de RAG; a geração de programa fica como extensão |
| Qwen3 sem modo de raciocínio | com raciocínio | Mesmo regime de geração nos três modelos; com raciocínio, o custo de saída do Qwen não seria comparável |
| Mesma precisão para todos os modelos | 4 bits só nos de 8B | Evita confundir porte do modelo com quantização |
| Métrica estrita como principal | só a tolerante | A tolerante dá margem a respostas pouco precisas; serve como análise de sensibilidade |

---

## 12. Estado da implementação

| Item | Estado |
|---|---|
| Download do dev e do teste; metadados (passos 1 × 2+, evidência, tamanho) | feito (notebook 01) |
| R0–R5, com tabelas de uma linha normalizadas e R3 no template do FinQA | feito (notebook 01) |
| Escolha de *k* no dev pela regra da seção 4 → **k = 4** | feito (notebook 01) |
| Parser: só após o último `Answer:`, falha de formato, estrita (×1, ×100) e tolerante (teto de 5%) | feito (notebook 01) |
| Verificações V1, V1b, V2, V3, V4, V6 | feito, todas passam (notebook 01) |
| Contagem de tokens do contexto, seis condições | feito para Qwen3 e Phi-4-mini; Llama **pendente** de `HF_TOKEN` |
| Prompt, few-shot (V5), piloto no dev (V7), tokens totais e de saída | **a fazer** (notebook 02) |
| Inferência, análise estatística, tipo de erro | **a fazer** (notebook 02 em diante) |
