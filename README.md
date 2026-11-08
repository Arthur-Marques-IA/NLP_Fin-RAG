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
| Representações | Markdown, JSON, Linearizada (frase por célula), Seletiva (top-k linhas, Markdown) + Gold (diagnóstico) |
| Fixos | texto do relatório, prompt, posição da pergunta, exemplos few-shot (do treino), temperatura 0 |
| Métrica | acurácia numérica com tolerância de arredondamento (gabarito `exe_ans`) |
| Custo | tokens de entrada pelo tokenizador de cada modelo; acurácia por mil tokens |
| Cortes | nº de passos do programa (1, 2, 3+), origem da evidência (tabela/texto/ambos), tamanho da tabela |

## Estrutura

```
notebooks/
  01_dados_representacoes.ipynb   # dados, metadados, serializações, avaliação e tokens
Engenharia de Contexto para RAG sobre Dados Tabulares.pdf   # proposta
Related_Work_RAG_Tabular_QA_Financeiro.pdf                  # revisão da literatura
```

## Primeiros resultados (notebook 01)

- **Composição do teste:** 654 perguntas de 1 passo, 409 de 2 e 84 de 3+; evidência em tabela (706), texto (283) ou ambos (158).
- **Seleção lexical (k=3):** preserva todas as linhas do gabarito em 76,4% das 855 perguntas com linhas de dados no gabarito (recall médio 0,85).
- **Avaliação:** o parser aceita o campo `answer` dos anotadores em 91,6% dos casos; o restante é ruído de anotação.
- **Custo (contexto completo, relativo ao Markdown):** JSON 1,13×, Linearizada 1,16×, Seletiva 0,93×, Gold 0,88×. A tabela é uma fração pequena do contexto (~150–190 de ~900–1.000 tokens), então a economia da seleção é modesta.

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
