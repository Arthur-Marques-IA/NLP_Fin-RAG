# Roteiro de execução no Colab

Este roteiro é para quem vai rodar o piloto e a inferência final em um ambiente do Google Colab com acelerador. Ele diz o que combinar antes, qual ambiente escolher, o que executar e o que fazer se a sessão cair. O desenho do estudo está em [METODOLOGIA.md](METODOLOGIA.md).

**Em resumo, para quem só vai executar:**

1. Adicione ao seu Drive o atalho da pasta `NLP - Checkpoints` (uma vez).
2. Guarde o token do Hugging Face nos *Secrets* do Colab, com o nome `HF_TOKEN`, e ligue o acesso do notebook.
3. Abra o notebook da etapa, escolha o acelerador combinado e use *Executar tudo*.

Pode parar e continuar quando quiser: os resultados são gravados na pasta do Drive a cada 4 perguntas e, ao rodar de novo, o notebook lê o que já existe lá e segue do ponto em que parou. Cada condição mostra uma barra de progresso com perguntas feitas, ritmo, tempo restante e quantas já estão gravadas.

## 1. O que será executado

| Etapa | Notebook | Gerações | Precisa de acelerador? |
|---|---|---|---|
| Piloto no dev e congelamento | `02_prompt_piloto.ipynb` | 300 por modelo (900 no total) | sim |
| Inferência no teste | `03_inferencia_teste.ipynb` | 6.882 por modelo (20.646 no total) | sim |
| Análise | `04_analise.ipynb` | nenhuma | não (CPU) |

Modelos: Llama 3.1 8B Instruct, Qwen3-8B e Phi-4-mini-instruct. Cada geração tem de 2.300 a 5.700 tokens de entrada e até 512 de saída (cerca de 100, em média).

## 2. Qual ambiente escolher

A precisão numérica é decidida **uma vez**, pela memória da GPU em que o piloto roda, e fica gravada no congelamento: 22 GB ou mais → **bf16**; menos que isso → **4 bits**. O teste tem de rodar na mesma precisão do piloto, e o notebook 03 recusa uma GPU em que ela não cabe.

| Opção no Colab | Memória | Precisão resultante | Recomendação |
|---|---|---|---|
| **GPU A100** | 40 GB | bf16 | **Primeira escolha.** Os três modelos cabem com folga em bf16, que é a precisão preferida da metodologia |
| **GPU G4** (RTX PRO 6000) | cerca de 96 GB (não conferido por nós) | bf16 | Equivalente à A100 para este estudo; use se a A100 não estiver disponível |
| GPU L4 | 24 GB | bf16 | Plano B. Os modelos de 8B ocupam cerca de 16 GB só de pesos; nos prompts mais longos pode faltar memória, e o lote é dividido automaticamente (fica registrado) |
| GPU T4 | 16 GB | 4 bits (NF4) | Funciona e já foi testada, mas é a mais lenta e muda a precisão do estudo |
| GPU H100 | 80 GB | bf16 | Serve, se estiver disponível na conta (na conta em que este roteiro foi escrito, aparecia desabilitada) |
| TPU v5e-1 / v6e-1 | 16 / 32 GB | — | **Não usar.** O código usa PyTorch com CUDA; na TPU não há quantização em 4 bits, os modelos de 8B não cabem na v5e-1 e a geração recompila a cada tamanho de prompt |
| CPU | — | — | Só para o notebook 04 |

Duas regras para não misturar condições:

- **Não troque de classe de GPU entre o piloto e o teste.** Piloto em A100/G4/L4 → teste em A100/G4/L4. Piloto em T4 → teste em T4.
- **Rode as seis condições de um mesmo modelo no mesmo tipo de GPU.** A comparação do estudo é entre representações dentro de cada modelo; a GPU de cada sessão fica registrada em `test/sessions.jsonl`.

### Tempo

Medido até agora só na T4 em 4 bits, com 16 a 48 perguntas da representação R1:

| Modelo | Tempo por pergunta (T4, 4 bits) | Teste completo, estimado (T4) |
|---|---|---|
| Phi-4-mini | 7 a 10 s | 13 a 19 h |
| Qwen3-8B | 11 a 13 s | 21 a 25 h |
| Llama 3.1 8B | não medido | parecido com o do Qwen3 |

Na A100 ou na G4 o tempo **não foi medido**; espera-se que seja várias vezes menor. A seção 7 do notebook 02 calcula a projeção real a partir do piloto, na GPU em que ele rodar. Vale combinar o total de horas depois desse número.

**O caminho em bf16 ainda não rodou com os modelos de 8B.** Ele foi exercitado só com o Phi-4-mini, na T4, em 8 perguntas (carregou, gerou, gravou no Drive e não teve falha de formato; a T4 não acelera bf16, então o tempo medido ali não serve de referência). O prompt e o parser foram ajustados na T4, em 4 bits. O piloto na GPU escolhida é a primeira execução real em bf16, e é por isso que ele vem antes de qualquer hora reservada para o teste: se um modelo reprovar na V7 (falha de formato de 5% ou mais em R1), ele fica fora do congelamento e o prompt volta a ser ajustado no dev.

## 3. O que combinar antes

1. **Acelerador e horas.** Qual opção da tabela acima será usada e por quanto tempo. Reserve primeiro uma sessão curta para o piloto (900 gerações); o total do teste sai da projeção que ele calcula.
2. **Pasta de resultados.** Tudo é gravado na pasta `NLP - Checkpoints` do Google Drive. Quem executa precisa de acesso de **editor** a ela (o dono da pasta envia o link em particular).
3. **Acesso ao Llama 3.1.** O modelo é restrito. A conta do Colab que executa precisa de um token do Hugging Face com acesso a `meta-llama/Llama-3.1-8B-Instruct`, guardado nos *Secrets* do Colab. O token **não** entra no código nem no repositório, que é público. Ele tem de continuar válido até o teste do Llama terminar: cada sessão nova baixa o modelo de novo.
4. **Parada depois do piloto.** O teste só começa depois que o relatório do piloto (seções 6 a 8 do notebook 02) for conferido. Depois que existe resultado do teste, o prompt e a configuração não podem mais mudar.
5. **Quem roda o quê.** Se houver mais de uma sessão ou conta, a divisão é **por modelo** (seção 5). Duas sessões nunca rodam o mesmo modelo ao mesmo tempo.

## 4. Preparação (uma vez por conta do Colab)

1. **Atalho da pasta no Drive.** Abra o link da pasta `NLP - Checkpoints`, clique no nome dela → **Organizar → Adicionar atalho** → **Meu Drive**. O atalho tem de ficar com o nome `NLP - Checkpoints`. (O dono da pasta não precisa deste passo.)
2. **Token do Hugging Face.** No Colab, ícone de chave (**Secrets**) → novo segredo com o nome `HF_TOKEN` e o valor do token → ative **Acesso do notebook**. O segredo é da conta, mas o acesso é ligado **em cada notebook**: ative-o no 02 e de novo no 03.
3. **Notebook.** Abra pelo GitHub, para rodar o código publicado:
   - piloto: `https://colab.research.google.com/github/Arthur-Marques-IA/NLP_Fin-RAG/blob/main/notebooks/02_prompt_piloto.ipynb`
   - teste: `https://colab.research.google.com/github/Arthur-Marques-IA/NLP_Fin-RAG/blob/main/notebooks/03_inferencia_teste.ipynb`
4. **Ambiente.** *Ambiente de execução → Alterar o tipo de ambiente de execução* → acelerador combinado.

## 5. Execução

### Etapa 1 — piloto e congelamento (notebook 02)

1. *Ambiente de execução → Executar tudo*. Autorize o acesso ao Google Drive quando o Colab pedir.
2. Confira a primeira célula:
   - `Resultados em:` tem de apontar para `.../NLP - Checkpoints/results`. Se a célula parar com `Pasta 'NLP - Checkpoints' não encontrada`, o atalho da pasta não foi criado (passo 1 da preparação): crie o atalho e rode de novo;
   - `HF_TOKEN: definido`. Sem ele, o Llama 3.1 é pulado.
3. Espere o fim. A seção 6 mostra a **V7** de cada modelo (`PASSA`, `FALHA` ou `INCOMPLETO`); a seção 7, as horas estimadas para o teste; a seção 8 grava `frozen_config.json`.
4. Envie ao responsável pelo estudo a saída das seções 6, 7 e 8. **Não comece o teste antes da confirmação.**

### Etapa 2 — teste (notebook 03)

1. Mesmo tipo de ambiente da etapa 1. *Executar tudo*.
2. A seção 1 confere que o código é o do congelamento (todas as linhas com `OK`). A seção 2 mostra o andamento: perguntas já gravadas por modelo × condição.
3. A seção 3 gera as respostas, um modelo por vez. Para dividir o trabalho entre sessões ou contas, troque na célula de configuração:

   ```python
   MODELS_TO_RUN = ["phi4-mini"]        # ou ["qwen3-8b"], ou ["llama3.1-8b"]; None roda todos
   ```

4. Termina quando a seção 4 mostra `Tudo completo.` Os resultados já estão no Drive; não há nada para enviar.

## 6. Se a sessão cair

Abra o mesmo notebook e rode tudo de novo. Não é preciso apagar nem ajustar nada:

- os resultados são gravados no Drive a cada lote de 4 perguntas (`SAVE_EVERY = 1`, na célula de configuração; um valor maior grava a cada N lotes e perde até N lotes em uma queda brusca);
- o que já foi gravado é pulado, e um modelo completo nem é carregado;
- perde-se, no máximo, o lote que estava em andamento;
- os lotes restantes têm a mesma composição que teriam sem a queda, então o resultado final é o mesmo.

Para acompanhar de fora, a tabela de andamento (seção 2 do notebook 03, ou o início da seção 5 do notebook 02) mostra quanto falta.

## 7. O que não fazer

- Não edite o prompt, os exemplos, o tamanho do lote nem a precisão no notebook 03. Ele só executa o que foi congelado.
- Não apague nem mova arquivos de `NLP - Checkpoints/results` enquanto houver sessão rodando.
- Não rode o mesmo modelo em duas sessões ao mesmo tempo: as duas escreveriam no mesmo arquivo.
- Não cole o token do Hugging Face em células nem em arquivos do repositório.
- Não use os ambientes de TPU.

## 8. O que fica gravado

Na pasta `NLP - Checkpoints/results`:

| Arquivo | Conteúdo |
|---|---|
| `pilot_dev/<modelo>__<representação>.jsonl` | respostas do piloto |
| `pilot_dev/revisions.json` | versão exata de cada modelo no Hugging Face |
| `tokens_prompt_test.csv` | tokens de entrada por pergunta, modelo e representação |
| `frozen_config.json` | prompt, precisão, lote e modelos congelados |
| `test/<modelo>__<representação>.jsonl` | respostas do teste (uma linha por pergunta) |
| `test/sessions.jsonl` | GPU, versões e commit de cada sessão |
| `analise/` | tabelas e figuras do notebook 04 |
