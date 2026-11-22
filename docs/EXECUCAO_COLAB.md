# Roteiro de execução no Colab

Este roteiro é para quem vai rodar o congelamento e a inferência final no Google Colab. Ele diz o que falta fazer, qual ambiente escolher, o que executar e o que fazer se a sessão cair. O desenho do estudo está em [METODOLOGIA.md](METODOLOGIA.md).

**Em resumo, para quem só vai executar:**

1. Adicione ao seu Drive o atalho da pasta `NLP - Checkpoints` (uma vez).
2. Abra o notebook da etapa, escolha o ambiente indicado e use *Executar tudo*.

Não é preciso token do Hugging Face: os dois modelos do estudo são abertos.

Pode parar e continuar quando quiser: os resultados são gravados na pasta do Drive a cada 4 perguntas e, ao rodar de novo, o notebook lê o que já existe lá e segue do ponto em que parou. Cada condição mostra uma barra de progresso com perguntas feitas, ritmo, tempo restante e quantas já estão gravadas.

## 1. O que falta executar

Modelos do estudo: **Qwen3-8B** e **Phi-4-mini-instruct**. O Llama 3.1 8B passou no piloto, mas ficou fora por tempo de GPU.

| Etapa | Notebook | Gerações | Ambiente | Estado |
|---|---|---|---|---|
| Piloto no dev | `02_prompt_piloto.ipynb` | 300 por modelo | — | **feito** (bf16, GPU L4) |
| Congelamento | `02_prompt_piloto.ipynb` | nenhuma | CPU | **falta** (seção 2) |
| Inferência no teste | `03_inferencia_teste.ipynb` | 6.882 por modelo (13.764 no total) | GPU com 22 GB ou mais | **falta** (seção 4) |
| Análise | `04_analise.ipynb` | nenhuma | CPU | falta |

Cada geração tem de 2.300 a 5.700 tokens de entrada e até 512 de saída (cerca de 130, em média).

## 2. Congelar com o piloto que já existe (sem GPU)

O piloto com o prompt do repositório (hash `bd940bbf875bc8e1`) já rodou em bf16 e os dois modelos passam na V7. Os arquivos estão no Drive, em `results/pilot_dev_old_bd940bbf/`.

1. No Drive, dentro de `NLP - Checkpoints/results/`: renomeie a pasta `pilot_dev` atual (por exemplo, para `pilot_dev_old_34ab34dd`) e renomeie `pilot_dev_old_bd940bbf` para `pilot_dev`. Mova, não apague.
2. Abra o notebook 02 e troque o ambiente para **CPU** (*Ambiente de execução → Alterar o tipo de ambiente de execução*).
3. *Executar tudo* e autorize o Google Drive. Como o piloto está completo, nenhum modelo é carregado: as seções 6 a 8 leem os arquivos, mostram a V7 e gravam `frozen_config.json`.
4. Confira na seção 8: `Entram no congelamento: ['phi4-mini', 'qwen3-8b']` e `"precision": "bf16"`.

O que o notebook faz se a pasta estiver errada:

- `pilot_dev` com arquivos de outro prompt ou outra precisão → para com uma mensagem, **antes de gerar qualquer coisa**;
- `pilot_dev` vazia ou incompleta → para e avisa que o piloto já existe e que a pasta montada (ou o nome da pasta) deve estar errada. Ele **não** gera um piloto novo, a menos que `ALLOW_NEW_PILOT = True` seja definido de propósito.

Atenção: existem duas pastas `NLP - Checkpoints` no Drive. A que tem o piloto é a que contém `results/pilot_dev_old_bd940bbf/`; a outra só tem os experimentos iniciais. Deixe uma só com esse nome, ou o notebook pode montar a errada.

Os arquivos do Llama que estão na pasta do piloto são ignorados. As outras pastas `pilot_dev_old_*` são de versões de prompt descartadas, que não estão no repositório; não são usadas e podem ser arquivadas.

## 3. Qual ambiente escolher para o teste

O estudo é em **bf16**, a precisão do piloto, e o notebook 03 recusa uma GPU em que ela não cabe.

| Opção no Colab | Memória | Recomendação |
|---|---|---|
| **GPU A100** | 40 GB | **Primeira escolha.** Os dois modelos cabem com folga |
| **GPU G4** (RTX PRO 6000) | cerca de 96 GB (não conferido por nós) | Equivalente à A100 para este estudo |
| GPU H100 | 80 GB | Serve, se estiver disponível na conta |
| GPU L4 | 24 GB | Funciona e foi a do piloto. O Qwen3 ocupa cerca de 16 GB só de pesos; nos prompts mais longos falta memória e o lote é dividido automaticamente (fica registrado) |
| GPU T4 | 16 GB | **Não usar**: bf16 não cabe |
| TPU v5e-1 / v6e-1 | 16 / 32 GB | **Não usar.** O código usa PyTorch com CUDA, e na TPU a geração recompila a cada tamanho de prompt (avaliação pela documentação, sem medir) |

**Rode as seis condições de um mesmo modelo no mesmo tipo de GPU.** A comparação do estudo é entre representações dentro de cada modelo; a GPU de cada sessão fica registrada em um arquivo próprio em `test/sessions/`.

### Tempo

Medido no piloto, em uma L4 com bf16 e lote de 4:

| Ordem | Modelo | Tempo por pergunta | Teste completo, estimado |
|---|---|---|---|
| 1 | Qwen3-8B | 8 a 9 s | cerca de 16 h |
| 2 | Phi-4-mini | cerca de 6 s | cerca de 12 h |

Total: perto de 28 h de L4. Na A100 e na G4 o tempo não foi medido; em alguns pilotos os dois modelos rodaram a 2,4 s por pergunta, provavelmente em uma GPU mais rápida, mas a GPU dessas sessões não ficou registrada. A seção 7 do notebook 02 mostra a projeção.

O teste pode ser dividido em quantas sessões forem necessárias, e os dois modelos podem rodar ao mesmo tempo em duas sessões ou contas diferentes.

## 4. Rodar o teste (notebook 03)

### Preparação (uma vez por conta do Colab)

1. **Atalho da pasta no Drive.** Abra o link da pasta `NLP - Checkpoints` (o dono envia em particular; é preciso acesso de **editor**), clique no nome dela → **Organizar → Adicionar atalho → Meu Drive**. O atalho tem de ficar com o nome `NLP - Checkpoints`. O dono da pasta não precisa deste passo.
2. **Notebook.** Abra pelo GitHub, para rodar o código publicado:
   `https://colab.research.google.com/github/Arthur-Marques-IA/NLP_Fin-RAG/blob/main/notebooks/03_inferencia_teste.ipynb`
3. **Ambiente.** *Ambiente de execução → Alterar o tipo de ambiente de execução* → GPU da seção 3.

### Execução

1. *Ambiente de execução → Executar tudo*. Autorize o acesso ao Google Drive quando o Colab pedir.
2. Confira a primeira célula: `Resultados em:` tem de apontar para `.../NLP - Checkpoints/results`. Se ela parar com `Pasta 'NLP - Checkpoints' não encontrada`, o atalho não foi criado.
3. A seção 1 confere que o código é o do congelamento (todas as linhas com `OK`). A seção 2 mostra o andamento: perguntas já gravadas por modelo × condição.
4. No começo da seção 3, cada modelo passa por um teste de memória com o prompt mais longo de cada condição. Se a sessão parar aí com erro de memória, a GPU é pequena para esse modelo: use A100 ou G4.
5. A seção 3 gera as respostas, um modelo por vez: primeiro o Qwen3-8B, depois o Phi-4-mini. Para rodar um só (por exemplo, para dividir entre duas sessões), troque na célula de configuração:

   ```python
   MODELS_TO_RUN = ["phi4-mini"]        # ou ["qwen3-8b"]; None roda os dois, nessa ordem
   ```

6. Termina quando a seção 4 mostra `Tudo completo.` Os resultados já estão no Drive; não há nada para enviar.

## 5. Se a sessão cair

Abra o mesmo notebook e rode tudo de novo. Não é preciso apagar nem ajustar nada:

- os resultados são gravados no Drive a cada lote de 4 perguntas (`SAVE_EVERY = 1`, na célula de configuração; um valor maior grava a cada N lotes e perde até N lotes em uma queda brusca);
- o que já foi gravado é pulado, e um modelo completo nem é carregado;
- perde-se, no máximo, o lote que estava em andamento;
- os lotes restantes têm a mesma composição que teriam sem a queda, então o resultado final é o mesmo.

## 6. O que não fazer

- Não edite o prompt, os exemplos, o tamanho do lote, o limite de tokens nem a precisão. O notebook 03 só executa o que foi congelado, e depois que existe resultado do teste nada disso pode mudar.
- Não rode nada com código que não está no GitHub. O congelamento e cada sessão registram o commit e se havia arquivo modificado sem commit; resultado gerado assim não entra no estudo.
- Não apague nem mova arquivos de `NLP - Checkpoints/results` enquanto houver sessão rodando.
- Não rode o mesmo modelo em duas sessões ao mesmo tempo: as duas escreveriam no mesmo arquivo.
- Não use T4 nem TPU.

## 7. Se o tempo acabar

O notebook 04 analisa os modelos que tiverem as **seis condições completas**. Por isso a ordem é Qwen3-8B primeiro: se só ele terminar, o estudo responde à pergunta para um modelo, com a limitação declarada de não poder dizer se o efeito vale para outro porte. Não corte perguntas nem representações: os contrastes e o poder estatístico do estudo dependem das 1.147 perguntas e das seis condições.

## 8. O que fica gravado

Na pasta `NLP - Checkpoints/results`:

| Arquivo | Conteúdo |
|---|---|
| `pilot_dev/<modelo>__<representação>.jsonl` | respostas do piloto |
| `pilot_dev/revisions.json` | versão exata de cada modelo no Hugging Face |
| `tokens_prompt_test.csv` | tokens de entrada por pergunta, modelo e representação |
| `frozen_config.json` | prompt, precisão, lote e modelos congelados |
| `test/<modelo>__<representação>.jsonl` | respostas do teste (uma linha por pergunta) |
| `test/sessions/<data>_<modelos>.json` | GPU, versões e commit de cada sessão (um arquivo por sessão) |
| `analise/` | tabelas e figuras do notebook 04 |
