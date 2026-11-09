# NLP Fin-RAG — Engenharia de Contexto para RAG sobre Dados Tabulares

Trabalho final de NLP (UFG). Estudo controlado de como a **forma de apresentar a tabela ao LLM** afeta a **acurácia** e o **custo em tokens** em perguntas numéricas sobre relatórios financeiros (FinQA), com modelos abertos de ~8B e sem ajuste fino.

## Pergunta de pesquisa

Em perguntas numéricas sobre relatórios financeiros, como a representação da tabela no prompt afeta a acurácia e o custo em tokens, e como esse efeito muda com a complexidade do raciocínio?

- **H1:** o formato altera a acurácia de modelos de ~8B no FinQA, e o melhor formato pode variar entre modelos.
- **H2:** selecionar as linhas relevantes reduz tokens sem perder acurácia quando a seleção preserva os operandos, e perde acurácia quando os corta.
- **H3:** as diferenças entre representações crescem nas perguntas de mais passos e nas que exigem tabela e texto.

## Desenho experimental

| Item | Escolha |
|---|---|
| Dados | FinQA, conjunto de teste oficial (1.147 perguntas) |
| Modelos | Llama 3.1 8B Instruct, Qwen3-8B, Phi-4-mini-instruct |
| Representações | R0 Bruta (controle), R1 Markdown (referência), R2 JSON, R3 Linearizada (frase por célula), R4 Seletiva (top-k linhas, Markdown) + R5 Gold-tabela (diagnóstico) |
| Fixos | texto do relatório, prompt, posição da pergunta, exemplos few-shot (do treino), temperatura 0 |
| Métrica | acurácia de execução estrita (erro relativo ≤ 1%, gabarito `exe_ans`) + versão tolerante ao arredondamento como sensibilidade |
| Custo | tokens de entrada pelo tokenizador de cada modelo; acurácia por mil tokens |
| Cortes | nº de passos do programa (1, 2, 3+), origem da evidência (tabela/texto/ambos), tamanho da tabela |

## Estrutura

A metodologia completa — representações comparadas, controles, métricas, estatística e verificações — está em **[docs/METODOLOGIA.md](docs/METODOLOGIA.md)**, que é a referência do projeto.

```
docs/
  METODOLOGIA.md                  # como o estudo é conduzido (referência)
notebooks/
  01_dados_representacoes.ipynb   # dados, metadados, serializações, avaliação e tokens
Engenharia de Contexto para RAG sobre Dados Tabulares.pdf   # proposta
Related_Work_RAG_Tabular_QA_Financeiro.pdf                  # revisão da literatura
```

## Primeiros resultados (notebook 01)

- **Composição do teste:** 654 perguntas de 1 passo e 493 de 2+ (84 com 3+); evidência em tabela (706), texto (283) ou ambos (158).
- **k da seletiva escolhido no dev:** k = 4 (preserva todas as linhas do gabarito em 84,2% do dev). No teste, R4 coincide com R1 em 43% das perguntas; o subconjunto efetivo da H2 tem 488 perguntas (348 com seleção que preserva o gabarito, 140 que corta).
- **Avaliação:** acurácia estrita (≤ 1%) e tolerante (arredondamento, teto de 5%); aplicada ao campo `answer` dos anotadores, aceita 82,3% e 90,0% — os anotadores arredondam muito, por isso o prompt pede 2 casas decimais.
- **Verificações:** conteúdo igual em R0–R3, R3 = template do FinQA (99,7%), R4/R5 no formato de R1, seleção sem vazamento e texto fixo — todas passam no dev e no teste.
- **Custo (contexto, relativo a R1):** R0 0,96×, R2 1,13×, R3 1,18×, R4 0,95× (0,90× no subconjunto efetivo), R5 0,88×. A tabela é uma fração pequena do contexto, então a economia da seleção é modesta.

> Observação: o campo `ann_table_rows` do FinQA vem vazio em ~110 perguntas do teste; o notebook usa as chaves `table_i` de `gold_inds` como gabarito de linhas.

## Como rodar

1. Abra o notebook no Google Colab com runtime **GPU** (T4 ou superior).
2. Para o Llama 3.1 (modelo *gated*), adicione um token do Hugging Face com acesso ao modelo em **Secrets** do Colab com o nome `HF_TOKEN`.
3. Execute as células em ordem. O FinQA é baixado do repositório oficial ([czyssrs/FinQA](https://github.com/czyssrs/FinQA)) para `data/`.

### Opcional: controlar o Colab pelo Claude Code (colab-mcp)

O [colab-mcp](https://github.com/googlecolab/colab-mcp) permite que um agente local edite e execute células do notebook aberto no navegador. Ele exige Python ≥ 3.13:

```bash
uv tool install --python 3.13 git+https://github.com/googlecolab/colab-mcp
claude mcp add --scope project colab-mcp -- colab-mcp
```

Instalar como ferramenta (em vez de `uvx git+...`) evita o timeout de 30 s na inicialização do servidor.

## Próximos passos

1. Prompt fixo com few-shot retirado do treino do FinQA.
2. Inferência com os três modelos (8B em 4 bits na T4).
3. Acurácia por modelo × representação com IC por bootstrap pareado e cortes por passos, evidência e tamanho.
4. Análise de erros: extração vs. cálculo.
