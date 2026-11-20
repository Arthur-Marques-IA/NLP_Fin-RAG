"""finrag — código compartilhado pelos notebooks 02–04.

Estudo: representação de tabelas em QA financeiro (FinQA). A referência do estudo é
docs/METODOLOGIA.md; este módulo a implementa.

As seções 1–4 (dados, metadados, representações, avaliação) são CÓPIA do notebook 01,
que continua sendo o lugar onde elas são explicadas e verificadas. O script
tests/test_consistencia.py confere que as duas versões produzem exatamente as mesmas
strings em todas as tabelas do dev e do teste. Se alterar uma, altere a outra.

As seções 5–9 (few-shot, prompt, tipo de erro, geração, estatística) são novas.
`torch` e `transformers` só são importados dentro das funções de geração, para que o
notebook de análise rode em CPU sem eles.
"""
import hashlib
import json
import math
import pathlib
import random
import re
import time
import urllib.request

# =====================================================================================
# 1. Dados
# =====================================================================================
FINQA_BASE = "https://raw.githubusercontent.com/czyssrs/FinQA/main/dataset/"


def load_finqa(split, data_dir="data"):
    """Baixa (se preciso) e carrega um split oficial do FinQA: 'train', 'dev' ou 'test'."""
    data_dir = pathlib.Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"finqa_{split}.json"
    if not path.exists():
        urllib.request.urlretrieve(FINQA_BASE + f"{split}.json", path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# =====================================================================================
# 2. Metadados por pergunta (cópia do notebook 01, seção 2)
# =====================================================================================
OP_RE = re.compile(r"[a-z_]+\(")

def count_steps(program: str) -> int:
    return len(OP_RE.findall(program))

def evidence_source(gold_inds: dict) -> str:
    kinds = {k.split("_")[0] for k in gold_inds}
    if kinds == {"table"}:
        return "table"
    if kinds == {"text"}:
        return "text"
    return "both"

def n_data_rows(table):
    # tabela de uma linha só: essa linha é dado (ver normalize_table na seção 3)
    return len(table) - 1 if len(table) > 1 else len(table)


# =====================================================================================
# 3. Representações da tabela R0–R5 (cópia do notebook 01, seção 3)
# =====================================================================================
def _header_names(header):
    """Nomes de coluna únicos; a primeira coluna vazia vira 'item'."""
    names, seen = [], {}
    for i, h in enumerate(header):
        name = h.strip() or ("item" if i == 0 else f"col_{i}")
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        names.append(name)
    return names

def _pad(row, n):
    return list(row) + [""] * (n - len(row))

def _cell(c):
    return str(c).strip()

def normalize_table(table):
    """Tabela de uma linha só (4 perguntas do teste): essa linha é dado, com cabeçalho vazio.
    Sem isso, R2 e R3 sairiam vazias e perderiam todo o conteúdo."""
    if len(table) == 1:
        return [[""] * len(table[0]), table[0]]
    return table

def to_raw(table):
    """R0: células não vazias separadas por espaço, uma linha por linha da tabela."""
    lines = [" ".join(_cell(c) for c in row if _cell(c)) for row in table]
    return "\n".join(l for l in lines if l)

def to_markdown(table):
    """R1 (e base de R4/R5)."""
    if not table:
        return ""
    n = max(len(r) for r in table)
    header = _header_names(_pad(table[0], n))
    esc = lambda c: _cell(c).replace("|", "\\|")
    lines = ["| " + " | ".join(map(esc, header)) + " |",
             "|" + "|".join(["---"] * n) + "|"]
    lines += ["| " + " | ".join(map(esc, _pad(r, n))) + " |" for r in table[1:]]
    return "\n".join(lines)

def to_json(table):
    """R2: lista de objetos, um por linha de dados."""
    if not table:
        return "[]"
    n = max(len(r) for r in table)
    header = _header_names(_pad(table[0], n))
    rows = [dict(zip(header, map(_cell, _pad(r, n)))) for r in table[1:]]
    return json.dumps(rows, ensure_ascii=False)

def linearize_row(header, row):
    """Frases de uma linha no template do FinQA, reproduzido à risca:
    '[<cabeçalho da coluna 0>] the <linha> of <coluna> is <valor> ; ...'
    (coluna sem nome: 'the <linha> of is <valor> ;', como no FinQA).
    Linha só com rótulo (ex.: título de seção) vira '<rótulo> ;'. Valores nunca são alterados."""
    n = max(len(header), len(row))
    header, row = _pad(header, n), _pad(row, n)
    label = _cell(row[0])
    sents = []
    for col, val in zip(header[1:], row[1:]):
        if _cell(val):
            of_col = f"of {_cell(col)}" if _cell(col) else "of"
            sents.append(f"the {label} {of_col} is {_cell(val)} ;")
    if not sents and label:
        sents = [f"{label} ;"]
    if _cell(header[0]) and sents:
        sents[0] = f"{_cell(header[0])} {sents[0]}"
    return sents

def to_linearized(table):
    """R3: uma frase por célula."""
    if not table:
        return ""
    return "\n".join(s for r in table[1:] for s in linearize_row(table[0], r))

# --- Gabarito de linhas (R5) ---
def gold_table_rows(ex):
    """Linhas de tabela do gabarito, a partir das chaves 'table_i' de gold_inds.
    (ann_table_rows vem vazio em ~110 perguntas do teste; gold_inds é mais completo.)"""
    return sorted(int(k.split("_")[1]) for k in ex["qa"]["gold_inds"] if k.startswith("table_"))

# --- Seleção de linhas (R4), sem gabarito ---
STOPWORDS = set("""a an the of in on for to by and or is are was were be been what which how
much many did does do from with as at that this these those its it their than then
percent percentage change total amount value values ratio year years""".split())
TOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?")

def _terms(text):
    return [t for t in TOKEN_RE.findall(str(text).lower()) if t not in STOPWORDS]

def select_rows(table, question, k):
    """Índices (>=1) das k linhas com maior sobreposição com a pergunta, na ordem original.
    Empate: a linha que vem antes. Recebe SÓ a tabela e a pergunta."""
    q = set(_terms(question))
    scored = []
    for i, row in enumerate(table[1:], start=1):
        terms = set(_terms(" ".join(map(str, row))))
        score = sum(2.0 if t.isdigit() else 1.0 for t in q & terms)
        scored.append((score, i))
    top = sorted(scored, key=lambda s: (-s[0], s[1]))[:k]
    return sorted(i for _, i in top)

def subtable(table, row_ids):
    """Cabeçalho (linha 0) sempre incluído + linhas pedidas, na ordem original."""
    return [table[0]] + [table[i] for i in sorted(set(row_ids)) if 0 < i < len(table)]

REPRESENTATIONS = ["raw", "markdown", "json", "linearized", "selective", "gold"]
REP_CODE = dict(zip(REPRESENTATIONS, ["R0", "R1", "R2", "R3", "R4", "R5"]))

def serialize(ex, rep, k):
    t = normalize_table(ex["table"])
    if rep == "raw":        return to_raw(t)
    if rep == "markdown":   return to_markdown(t)
    if rep == "json":       return to_json(t)
    if rep == "linearized": return to_linearized(t)
    if rep == "selective":  return to_markdown(subtable(t, select_rows(t, ex["qa"]["question"], k)))
    if rep == "gold":
        rows = gold_table_rows(ex)
        if len(ex["table"]) == 1:          # linha 0 original virou a linha 1
            rows = [i + 1 for i in rows]
        return to_markdown(subtable(t, rows))
    raise ValueError(rep)

def build_context(ex, rep, k):
    """Texto do relatório fixo; só o bloco da tabela muda entre representações."""
    pre = " ".join(ex["pre_text"])
    post = " ".join(ex["post_text"])
    return f"{pre}\n\nTable:\n{serialize(ex, rep, k)}\n\n{post}".strip()


# --- Preservação do gabarito pela seleção (cópia do notebook 01, seção 3.1) ---
K_CANDIDATES = (1, 2, 3, 4, 5)
K_THRESHOLD = 0.80
K_FROZEN = 4          # escolhido no dev pela regra da seção 4 da metodologia

def gold_data_rows(ex):
    return {i for i in gold_table_rows(ex) if i > 0}   # linha 0 (cabeçalho) sempre entra

def gold_preserved(ex, k):
    """True/False se a seleção com k mantém todas as linhas do gabarito; None se não há linha a preservar."""
    gold = gold_data_rows(ex)
    if not gold:
        return None
    return gold <= set(select_rows(ex["table"], ex["qa"]["question"], k))


# =====================================================================================
# 4. Avaliação — acurácia estrita e tolerante (cópia do notebook 01, seção 4)
# =====================================================================================
ANSWER_RE = re.compile(r"answer\s*[:：]", re.I)
NUM_RE = re.compile(r"\(?\s*[-−]?\s*\$?\s*[-−]?\s*(?:\d[\d,]*(?:\.\d+)?|\.\d+)\s*%?\s*\)?")
LEAD_RE = re.compile(r"[\s*_`\"'\[]*(?:(?:approximately|approx\.?|about|around|roughly)\s+|[~≈]\s*)?", re.I)
UNIT_RE = re.compile(r"\s*(thousand|million|billion|trillion)\b", re.I)
UNITS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
REL_TOL_STRICT = 0.01
REL_TOL_LENIENT = 0.05

def answer_segment(text):
    """Linha da resposta: o texto após o ÚLTIMO 'Answer:', até o fim da linha (a primeira linha
    não vazia, se o modelo quebrou a linha depois dos dois-pontos). None se não houver 'Answer:'."""
    if text is None:
        return None
    ms = list(ANSWER_RE.finditer(str(text)))
    if not ms:
        return None
    lines = [l for l in str(text)[ms[-1].end():].splitlines() if l.strip()]
    return lines[0] if lines else ""

def parse_number(segment):
    """(valor, casas_decimais, fator_da_unidade) da linha da resposta; None se ela não começa por um número.

    - o número tem de vir no INÍCIO da linha (depois de `$`, parêntese, sinal, negrito ou "approximately").
      Uma frase ("The amount cannot be determined after October 29") não é resposta, mesmo com números;
    - se a linha é uma conta ("30 + 29 = 59"), vale o que vem depois do último "=" (ou "≈");
    - fator_da_unidade é 1e3, 1e6, 1e9 ou 1e12 se o número vem seguido de thousand/million/billion/trillion;
      None caso contrário."""
    if segment is None:
        return None
    seg = re.split("[=≈]", segment)[-1]
    m = NUM_RE.match(seg, LEAD_RE.match(seg).end())
    if not m:
        return None
    tok = m.group(0).strip()
    neg = (tok.startswith("(") and tok.endswith(")")) or bool(re.match(r"[($\s]*[-−]", tok))
    digits = re.sub(r"[^\d.]", "", tok)
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    val = float(digits)
    unit = UNIT_RE.match(seg, m.end())
    return (-val if neg else val), decimals, (UNITS[unit.group(1).lower()] if unit else None)

def parse_yes_no(segment):
    if segment is None:
        return None
    m = re.search(r"\b(yes|no)\b", segment.lower())
    return m.group(1) if m else None

def _rel_err(pred, g):
    return abs(pred - g) / abs(g) if g != 0 else (0.0 if pred == 0 else math.inf)

def evaluate(pred_text, gold):
    """Retorna dict(format_ok, strict, lenient, pred)."""
    seg = answer_segment(pred_text)
    if isinstance(gold, str):                       # sim/não
        yn = parse_yes_no(seg)
        ok = yn == gold.strip().lower()
        return {"format_ok": yn is not None, "strict": ok, "lenient": ok, "pred": yn}
    p = parse_number(seg)
    if p is None:
        return {"format_ok": False, "strict": False, "lenient": False, "pred": None}
    pred, dec, unit = p
    scales = (gold, gold * 100)                    # x1 e porcentagem escrita como número
    if unit:                                       # "7,301 million" também vale para 7301000000
        scales += (gold / unit,)
    strict = any(_rel_err(pred, g) <= REL_TOL_STRICT for g in scales)
    lenient = strict or any(
        pred != 0 and (pred > 0) == (g > 0)
        and math.isclose(round(g, dec), pred, abs_tol=1e-9)
        and _rel_err(pred, g) <= REL_TOL_LENIENT
        for g in scales)
    return {"format_ok": True, "strict": strict, "lenient": lenient, "pred": pred}

# Casos da tabela 6.1 de docs/METODOLOGIA.md + extras: (saída, gabarito, estrita, tolerante, formato_ok)
PARSER_TESTS = [
    ("Answer: 94.00", 94.0, True, True, True),
    ("Answer: 14.46%", 0.14464, True, True, True),
    ("Answer: 14.46", 0.14464, True, True, True),
    ("Answer: 14%", 0.14464, False, True, True),
    ("Answer: (32.00)", -32.0, True, True, True),
    ("Answer: -32.00", -32.0, True, True, True),
    ("Answer: 1", 1.4, False, False, True),
    ("Answer: 10", 9.6, False, True, True),
    ("Answer: 0.94", 94.0, False, False, True),
    ("Answer: 0", 0.4, False, False, True),
    ("Answer: 0.35%", -0.00357, False, False, True),
    ("Answer: $1,234.50", 1234.5, True, True, True),
    ("Answer: .385", 0.38537, True, True, True),
    ("In 2015 revenue grew.\nAnswer: 94.00", 94.0, True, True, True),
    ("answer: 5.00\nWait, recheck.\nAnswer: 94.00", 94.0, True, True, True),
    ("There was no change. Answer: yes", "yes", True, True, True),
    ("Answer: no", "yes", False, False, True),
    ("The answer is 94", 94.0, False, False, False),
    ("Answer: cannot be determined", 94.0, False, False, False),
    # Casos vistos nas saídas reais dos modelos (dev), que a primeira versão do parser lia errado
    ("Answer: $ 30 + $ 29 + $ 94 + $ 62 + $ 145 + $ 23 + $ 78 = $ 560 million", 560.0, True, True, True),
    ("0.2163 * 100 = 21.63%\nAnswer: 2313 / 10690 = 21.63%", 0.21637, True, True, True),
    ("Answer: 524804 / 531822 ≈ 0.9867", 0.98680, True, True, True),
    ("Answer: $7,301 million", 7301000000.0, True, True, True),
    ("Answer: 9119 million", 9119.0, True, True, True),
    ("Answer: 7301.00", 7301000000.0, False, False, True),
    ("Answer: 2.3 billion", 2300.0, False, False, True),
    ("Answer: The amount cannot be determined for the period after October 29, 2011.", 2.3345, False, False, False),
    ("Answer: The revenues were $2573 million for 2016 and $3781 million for 2015.", 2573.0, False, False, False),
    ("Answer: 20.93% of the owned facilities are located in Europe.", 0.2093, True, True, True),
    ("Answer: -$444.20", -444.2, True, True, True),
    ("Answer: $ -444.20", -444.2, True, True, True),
    ("Answer: approximately 5.2%", 0.052, True, True, True),
    ("Answer: **94.00**", 94.0, True, True, True),
    ("Answer:\n94.00", 94.0, True, True, True),
    ("Answer: 94.00\nNote: in 2015 it was 80.", 94.0, True, True, True),
    ("Answer: 80\nIn 2015 it was 94.", 94.0, False, False, True),
    ("Answer: no", 94.0, False, False, False),
]



# =====================================================================================
# 5. Metadados em tabela e verificações V1–V4, V6 (mesma lógica do notebook 01)
# =====================================================================================
def build_meta(examples, k=K_FROZEN):
    """Uma linha por pergunta, com as variáveis de corte da análise (seção 7 da metodologia)."""
    import pandas as pd
    rows = []
    for ex in examples:
        n_steps = count_steps(ex["qa"]["program"])
        n_rows = n_data_rows(ex["table"])
        preserved = gold_preserved(ex, k)
        rows.append({
            "id": ex["id"],
            "n_steps": n_steps,
            "steps_main": "1" if n_steps == 1 else "2+",
            "steps_bin": {1: "1", 2: "2"}.get(n_steps, "3+"),
            "evidence": evidence_source(ex["qa"]["gold_inds"]),
            "n_rows": n_rows,
            "table_size": f"até {k} linhas" if n_rows <= k else f"mais de {k} linhas",
            "gold_answer": ex["qa"]["exe_ans"],
            "is_yes_no": isinstance(ex["qa"]["exe_ans"], str),
            "has_gold_rows": preserved is not None,
            "gold_preserved": preserved,
            "effective_h2": preserved is not None and n_rows > k,
        })
    return pd.DataFrame(rows)


def choose_k(dev):
    """Regra da seção 4: menor k com todas as linhas do gabarito preservadas em >= 80% do dev."""
    rates = {}
    for k in K_CANDIDATES:
        flags = [p for p in (gold_preserved(ex, k) for ex in dev) if p is not None]
        rates[k] = sum(flags) / len(flags)
    k = next((k for k in K_CANDIDATES if rates[k] >= K_THRESHOLD), K_CANDIDATES[-1])
    return k, rates


def _content_items(table):
    """Valores, rótulos de linha, nomes de coluna com dados e cabeçalho da coluna 0."""
    table = normalize_table(table)
    if not table:
        return set()
    n = max(len(r) for r in table)
    header = _pad(table[0], n)
    items, cols_with_data = set(), set()
    for r in table[1:]:
        r = _pad(r, n)
        if _cell(r[0]):
            items.add(_cell(r[0]))
        for j in range(1, n):
            if _cell(r[j]):
                items.add(_cell(r[j]))
                cols_with_data.add(j)
    items |= {_cell(header[j]) for j in cols_with_data if _cell(header[j])}
    if _cell(header[0]) and len(table) > 1:
        items.add(_cell(header[0]))
    return items


def run_checks(examples, k=K_FROZEN):
    """V1, V1b, V2, V3, V4 e V6 da seção 8. Levanta AssertionError se alguma falhar."""
    import inspect
    out = {}
    v1 = []
    for ex in examples:
        items = _content_items(ex["table"])
        texts = {"raw": serialize(ex, "raw", k),
                 "markdown": serialize(ex, "markdown", k).replace("\\|", "|"),
                 "linearized": serialize(ex, "linearized", k)}
        jvals = set()
        for row in json.loads(serialize(ex, "json", k)):
            jvals |= set(row.keys()) | set(row.values())
        for it in items:
            v1 += [(ex["id"], rep, it) for rep, txt in texts.items() if it not in txt]
            if not any(it == v or it in v for v in jvals):
                v1.append((ex["id"], "json", it))
        for rep in ("raw", "markdown", "json", "linearized"):
            if not serialize(ex, rep, k).strip("[] \n") and items:
                v1.append((ex["id"], rep, "<vazia>"))
    out["V1  conteúdo igual em R0–R3 (falhas)"] = len(v1)
    assert not v1, v1[:5]

    squash = lambda s: re.sub(r"\s+", "", s)
    tot = hit = 0
    for ex in examples:
        for key, txt in ex["qa"]["gold_inds"].items():
            if key.startswith("table_") and int(key.split("_")[1]) > 0:
                i = int(key.split("_")[1])
                tot += 1
                hit += squash(" ".join(linearize_row(ex["table"][0], ex["table"][i]))) == squash(txt)
    out["V1b R3 = template do FinQA"] = f"{hit}/{tot} ({hit / tot:.1%})"
    assert hit / tot >= 0.99

    v2 = []
    for ex in examples:
        full = serialize(ex, "markdown", k).split("\n")
        for rep in ("selective", "gold"):
            sub = serialize(ex, rep, k).split("\n")
            it = iter(full[2:])
            if sub[:2] != full[:2] or not all(line in it for line in sub[2:]):
                v2.append((ex["id"], rep))
    out["V2  R4/R5 = subtabela de R1 (falhas)"] = len(v2)
    assert not v2, v2[:5]

    assert list(inspect.signature(select_rows).parameters) == ["table", "question", "k"]
    v3 = [ex["id"] for ex in examples
          if serialize({"table": ex["table"], "qa": {"question": ex["qa"]["question"]}}, "selective", k)
          != serialize(ex, "selective", k)]
    out["V3  seletiva independente do gabarito (falhas)"] = len(v3)
    assert not v3, v3[:5]

    v4 = []
    for ex in examples:
        outside = set()
        for rep in REPRESENTATIONS:
            ctx, tab = build_context(ex, rep, k), serialize(ex, rep, k)
            head, sep, tail = ctx.partition("\nTable:\n")
            assert sep and tail.startswith(tab)
            outside.add((head, tail[len(tab):]))
        if len(outside) != 1:
            v4.append(ex["id"])
    out["V4  texto idêntico fora da tabela (falhas)"] = len(v4)
    assert not v4, v4[:5]

    bad = [t for t, g, s, l, f in PARSER_TESTS
           if (evaluate(t, g)["strict"], evaluate(t, g)["lenient"], evaluate(t, g)["format_ok"]) != (s, l, f)]
    out["V6  parser"] = f"{len(PARSER_TESTS) - len(bad)}/{len(PARSER_TESTS)} casos"
    assert not bad, bad
    return out


# =====================================================================================
# 6. Programas do gabarito: execução e operandos
# =====================================================================================
STEP_RE = re.compile(r"([a-z_]+)\(([^()]*)\)")
ARITH_OPS = {"add", "subtract", "multiply", "divide"}
TEXT_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


def parse_program(program):
    """Lista de (operação, [argumentos]) de um programa do FinQA."""
    return [(op, [a.strip() for a in args.split(",")]) for op, args in STEP_RE.findall(program)]


def _arg_kind(a):
    if re.fullmatch(r"#\d+", a):
        return "ref"
    if a.startswith("const_"):
        return "const"
    if re.fullmatch(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+", a):
        return "num"
    if re.fullmatch(r"-?\d[\d,]*(?:\.\d+)?%", a):
        return "pct"
    return "other"


def _arg_value(a, results):
    kind = _arg_kind(a)
    if kind == "ref":
        return results[int(a[1:])]
    if kind == "const":
        body = a[len("const_"):]
        return -float(body[1:]) if body.startswith("m") else float(body)
    if kind == "num":
        return float(a.replace(",", ""))
    if kind == "pct":
        return float(a[:-1].replace(",", "")) / 100
    raise ValueError(a)


def execute_program(program):
    """Executa programas aritméticos (add, subtract, multiply, divide, exp, greater).
    Retorna float, "yes"/"no", ou None se o programa usa operações de tabela."""
    results = []
    try:
        for op, args in parse_program(program):
            if op.startswith("table_"):
                return None
            a, b = (_arg_value(x, results) for x in args[:2])
            if op == "add":
                r = a + b
            elif op == "subtract":
                r = a - b
            elif op == "multiply":
                r = a * b
            elif op == "divide":
                r = a / b
            elif op == "exp":
                r = a ** b
            elif op == "greater":
                r = "yes" if a > b else "no"
            else:
                return None
            results.append(r)
    except (ValueError, ZeroDivisionError, IndexError, TypeError):
        return None
    return results[-1] if results else None


def numbers_in(text):
    """Números escritos em um texto, sem sinal: "5,735", "$ 151" e "14.1%" viram 5735.0, 151.0 e 14.1."""
    out = []
    for tok in TEXT_NUM_RE.findall(str(text)):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def _in_pool(value, pool):
    v = abs(value)
    return any(abs(v - p) <= 1e-6 * max(1.0, v) for p in pool)


def program_operands(ex):
    """Operandos numéricos do programa do gabarito; cada um é uma tupla de escritas aceitas.
    - número escrito no programa: o próprio valor;
    - porcentagem escrita no programa ("5%"): 5 ou 0.05;
    - referências "#n" e constantes "const_*" não contam (não são lidas do relatório);
    - operações de tabela ("table_sum(linha, none)"): os números da linha citada.
    Retorna None quando não há operando numérico identificável."""
    operands = []
    for op, args in parse_program(ex["qa"]["program"]):
        if op.startswith("table_"):
            label = args[0].strip().lower()
            rows = [r for r in normalize_table(ex["table"])[1:] if _cell(r[0]).lower() == label]
            if not rows:
                return None
            for cell in rows[0][1:]:
                nums = numbers_in(cell)
                if nums:
                    operands.append((nums[0],))
            continue
        for a in args:
            kind = _arg_kind(a)
            if kind == "num":
                operands.append((abs(float(a.replace(",", ""))),))
            elif kind == "pct":
                v = abs(float(a[:-1].replace(",", "")))
                operands.append((v, v / 100))
    return operands or None


def error_type(raw_output, ex, result):
    """Heurística da seção 6.4. `result` é a saída de evaluate().
    "" (acerto) | "formato" | "extração" (falta operando no raciocínio) |
    "cálculo" (todos os operandos aparecem) | "indefinido" (sem operando numérico identificável)."""
    if result["strict"]:
        return ""
    if not result["format_ok"]:
        return "formato"
    operands = program_operands(ex)
    if operands is None:
        return "indefinido"
    pool = numbers_in(raw_output)
    missing = [alts for alts in operands if not any(_in_pool(v, pool) for v in alts)]
    return "extração" if missing else "cálculo"


# =====================================================================================
# 7. Few-shot e prompt (seção 3 da metodologia)
# =====================================================================================
FEWSHOT_SEED = 2026
FEWSHOT_MAX_CONTEXT_CHARS = 3000
FEWSHOT_KINDS = ("table_1step", "both_2step", "text_only")


def fewshot_candidates(train, kind, k=K_FROZEN):
    """Perguntas do treino elegíveis para cada um dos três papéis de exemplo.
    Filtros comuns (seção 3.1 da metodologia): resposta numérica;
    programa só com add/subtract/multiply/divide sobre números, constantes e resultados
    anteriores; o programa executado reproduz `exe_ans`; a resposta dos anotadores bate com
    `exe_ans` na métrica estrita; todos os operandos aparecem no contexto; contexto (em R1)
    com até FEWSHOT_MAX_CONTEXT_CHARS caracteres; a seleção de linhas (R4) preserva as linhas
    do gabarito, para que a resposta do exemplo seja dedutível em todas as condições."""
    out = []
    for ex in train:
        qa = ex["qa"]
        gold = qa["exe_ans"]
        steps = parse_program(qa["program"])
        if isinstance(gold, str) or not steps:
            continue
        if any(op not in ARITH_OPS for op, _ in steps):
            continue
        if any(_arg_kind(a) not in ("num", "const", "ref") for _, args in steps for a in args):
            continue
        got = execute_program(qa["program"])
        if got is None or isinstance(got, str) or abs(got - gold) > 1e-4 * max(1.0, abs(gold)):
            continue
        if not evaluate("Answer: " + str(qa["answer"]), gold)["strict"]:
            continue
        context = build_context(ex, "markdown", k)
        if len(context) > FEWSHOT_MAX_CONTEXT_CHARS:
            continue
        pool = numbers_in(context)
        if not all(_in_pool(alts[0], pool) for alts in (program_operands(ex) or [])):
            continue
        if gold_preserved(ex, k) is False:      # a seletiva não pode cortar o gabarito do exemplo
            continue
        evidence, n_steps, n_rows = evidence_source(qa["gold_inds"]), len(steps), n_data_rows(ex["table"])
        is_pct = "%" in str(qa["answer"])
        ok = {
            "table_1step": evidence == "table" and n_steps == 1 and n_rows > k and not is_pct,
            "both_2step": evidence == "both" and n_steps == 2 and n_rows > k and is_pct,
            "text_only": evidence == "text" and n_steps in (1, 2),
        }[kind]
        if ok:
            out.append(ex)
    return sorted(out, key=lambda e: e["id"])


def draw_fewshot(train, seed=FEWSHOT_SEED, k=K_FROZEN):
    """Sorteia um exemplo por papel, com uma única semente. Retorna a lista de exemplos."""
    rng = random.Random(seed)
    return [rng.choice(fewshot_candidates(train, kind, k)) for kind in FEWSHOT_KINDS]


# Exemplos fixos: resultado de draw_fewshot(train) com FEWSHOT_SEED e os filtros acima;
# check_fewshot() confere que o sorteio reproduz estes IDs. (Houve um sorteio anterior, sem o
# filtro "a seleção preserva o gabarito"; ver a nota de transparência na seção 3.1 da metodologia.)
# O raciocínio de cada exemplo foi escrito à mão, é o mesmo nas seis condições e não cita o
# formato da tabela.
FEWSHOT_IDS = (
    "C/2017/page_205.pdf-1",      # 1 passo, evidência na tabela, resposta que não é porcentagem
    "C/2010/page_306.pdf-1",      # 2 passos, evidência na tabela e no texto, porcentagem
    "VLO/2015/page_24.pdf-2",     # evidência só no texto
)
FEWSHOT_SOLUTIONS = {
    "C/2017/page_205.pdf-1": (
        "Receivables from brokers, dealers and clearing organizations were 19169 at december 31, 2017, "
        "and payables to brokers, dealers and clearing organizations were 22601. 19169 / 22601 = 0.85\n"
        "Answer: 0.85"
    ),
    "C/2010/page_306.pdf-1": (
        "The report assumes 100 was invested at the end of 2005, and the citigroup value in 2010 is 11.22. "
        "11.22 - 100 = -88.78. -88.78 / 100 = -0.8878 = -88.78%\n"
        "Answer: -88.78%"
    ),
    "VLO/2015/page_24.pdf-2": (
        "The report says 1.3 billion remained available for purchase under the 2.5 billion program. "
        "1.3 / 2.5 = 0.52 = 52.00%\n"
        "Answer: 52.00%"
    ),
}

INSTRUCTION = (
    "You are a financial analyst. Answer the question using the report below.\n"
    "Think step by step briefly, then give the final answer on the last line as\n"
    "\"Answer: <number>\" with two decimals, in the same unit as the table\n"
    "(use % for percentages). For yes/no questions, write \"Answer: yes\" or \"Answer: no\"."
)
EXAMPLE_HEADER = "=== Example {i} ==="
TARGET_HEADER = "=== Now answer this one ==="
# Última linha do prompt, depois da pergunta-alvo. Sem ela, o Phi-4-mini terminava quase um terço das
# respostas sem a linha "Answer:". O texto foi escolhido entre três variantes, em 48 perguntas do dev
# fora do piloto (seção 3 da metodologia); citar sim/não evita "Answer: 100%" em pergunta de sim ou não.
FORMAT_REMINDER = ('Think step by step briefly, then end with the final line "Answer: <number>" '
                   '(or "Answer: yes" / "Answer: no").')
MAX_NEW_TOKENS = 512


def format_item(ex, rep, k=K_FROZEN):
    """Bloco de uma pergunta: relatório (com a tabela na representação `rep`) e a pergunta depois."""
    return f"Report:\n{build_context(ex, rep, k)}\n\nQuestion: {ex['qa']['question']}"


def build_prompt(ex, rep, shots, k=K_FROZEN):
    """Prompt completo de uma pergunta em uma condição. As tabelas dos exemplos usam a MESMA
    representação da condição; todo o resto é idêntico entre as condições."""
    parts = [INSTRUCTION]
    for i, shot in enumerate(shots, start=1):
        parts.append(f"{EXAMPLE_HEADER.format(i=i)}\n{format_item(shot, rep, k)}\n\n"
                     f"{FEWSHOT_SOLUTIONS[shot['id']]}")
    parts.append(f"{TARGET_HEADER}\n{format_item(ex, rep, k)}")
    parts.append(FORMAT_REMINDER)
    return "\n\n".join(parts)


def get_fewshot(train):
    """Os três exemplos fixos, na ordem de FEWSHOT_IDS."""
    by_id = {ex["id"]: ex for ex in train}
    return [by_id[i] for i in FEWSHOT_IDS]


def check_fewshot(train, dev, test, k=K_FROZEN):
    """V5 da seção 8. Levanta AssertionError se alguma parte falhar."""
    out = {}
    drawn = tuple(ex["id"] for ex in draw_fewshot(train, FEWSHOT_SEED, k))
    assert drawn == FEWSHOT_IDS, f"o sorteio deu {drawn}, mas os IDs fixos são {FEWSHOT_IDS}"
    out["V5a sorteio com a semente reproduz os IDs fixos"] = "ok"

    other = {ex["id"] for ex in dev} | {ex["id"] for ex in test}
    other_docs = {ex["filename"] for ex in dev} | {ex["filename"] for ex in test}
    shots = get_fewshot(train)
    assert not set(FEWSHOT_IDS) & other
    assert not {s["filename"] for s in shots} & other_docs
    out["V5b exemplos (e seus documentos) fora do dev e do teste"] = "ok"

    for shot in shots:
        sol = FEWSHOT_SOLUTIONS[shot["id"]]
        res = evaluate(sol, shot["qa"]["exe_ans"])
        assert res["strict"], (shot["id"], res)
        assert len(ANSWER_RE.findall(sol)) == 1
        written = numbers_in(sol)
        assert all(_in_pool(a[0], written) for a in program_operands(shot)), shot["id"]
        for rep in REPRESENTATIONS:              # a resposta é dedutível do contexto mostrado
            shown = numbers_in(build_context(shot, rep, k))
            assert all(_in_pool(a[0], shown) for a in program_operands(shot)), (shot["id"], rep)
    out["V5c resposta dos exemplos correta, com todos os operandos visíveis em cada condição"] = "ok"

    probes = (dev[:25] + test[:25])
    for ex in probes:
        skeletons = set()
        for rep in REPRESENTATIONS:
            prompt = build_prompt(ex, rep, shots, k)
            for item in shots + [ex]:
                block = "\nTable:\n" + serialize(item, rep, k) + "\n"
                assert prompt.count(block) >= 1, (ex["id"], rep, item["id"])
                prompt = prompt.replace(block, "\nTable:\n<TABELA>\n", 1)
            skeletons.add(prompt)
        assert len(skeletons) == 1, ex["id"]
    out["V5d entre condições, só os blocos de tabela mudam (exemplos na representação da condição)"] = \
        f"ok em {len(probes)} perguntas × 6 condições"
    return out


def prompt_hash(k=K_FROZEN):
    """Identifica o template: instrução, cabeçalhos, lembrete de formato, exemplos, respostas dos
    exemplos, k e limite de saída."""
    blob = json.dumps([INSTRUCTION, EXAMPLE_HEADER, TARGET_HEADER, FORMAT_REMINDER, FEWSHOT_IDS,
                       sorted(FEWSHOT_SOLUTIONS.items()), k, MAX_NEW_TOKENS], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def prompts_fingerprint(examples, shots, k=K_FROZEN):
    """Hash de TODOS os prompts (perguntas × 6 condições). Muda se qualquer coisa mudar:
    template, exemplos, serialização, seleção de linhas ou os próprios dados."""
    h = hashlib.sha256()
    for ex in examples:
        for rep in REPRESENTATIONS:
            h.update(build_prompt(ex, rep, shots, k).encode("utf-8"))
            h.update(b"\x00")
    return h.hexdigest()[:16]


# =====================================================================================
# 8. Geração (seções 3, 5 e 9 da metodologia)
# =====================================================================================
MODELS = {
    "llama3.1-8b": "meta-llama/Llama-3.1-8B-Instruct",
    "qwen3-8b":    "Qwen/Qwen3-8B",
    "phi4-mini":   "microsoft/Phi-4-mini-instruct",
}
PRECISIONS = ("4bit", "bf16", "cpu-fp32")      # "cpu-fp32" existe só para testes sem GPU


def chat_text(tokenizer, model_name, prompt):
    """Prompt como UMA mensagem de usuário, no chat template oficial do modelo.
    Qwen3 roda sem modo de raciocínio, para gerar no mesmo regime dos outros."""
    kwargs = {"enable_thinking": False} if model_name.startswith("qwen3") else {}
    return tokenizer.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False,
                                         add_generation_prompt=True, **kwargs)


def count_tokens(tokenizer, text):
    return len(tokenizer.encode(text, add_special_tokens=False))


def load_tokenizer(model_name, hf_token=None, revision=None):
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODELS.get(model_name, model_name), token=hf_token, revision=revision)
    tok.padding_side = "left"                   # geração em lote: o texto novo começa alinhado à direita
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    return tok


def resolve_revision(model_name, hf_token=None):
    """Commit atual do repositório do modelo no Hugging Face (None se não der para consultar)."""
    try:
        from huggingface_hub import model_info
        return model_info(MODELS.get(model_name, model_name), token=hf_token).sha
    except Exception:
        return None


def load_model(model_name, precision, hf_token=None, revision=None):
    """Carrega tokenizador e modelo. Retorna (tokenizer, model, revisão do repositório).
    Sem `revision`, usa o commit atual do repositório e o devolve, para ser congelado."""
    import torch
    import transformers
    from transformers import AutoModelForCausalLM
    assert precision in PRECISIONS, precision
    revision = revision or resolve_revision(model_name, hf_token)
    tok = load_tokenizer(model_name, hf_token, revision)
    version = tuple(int(x) for x in re.findall(r"\d+", transformers.__version__)[:2])
    dtype_key = "dtype" if version >= (4, 56) else "torch_dtype"
    kwargs = {"token": hf_token, "revision": revision}
    if precision == "4bit":
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)
        # As partes não quantizadas (embeddings, normalizações) e as ativações ficam em fp16, o mesmo
        # tipo do cálculo dos pesos de 4 bits. Sem isso, o transformers 5 carrega no tipo do checkpoint
        # (bf16), que a T4 não acelera: no Phi-4-mini medimos o dobro do tempo e 13,5 GB em vez de
        # 5,7 GB de pico num lote de 4 prompts de ~2.900 tokens.
        kwargs[dtype_key] = torch.float16
        kwargs["device_map"] = {"": 0}
    elif precision == "bf16":
        kwargs[dtype_key] = torch.bfloat16
        kwargs["device_map"] = {"": 0}
    model = AutoModelForCausalLM.from_pretrained(MODELS.get(model_name, model_name), **kwargs)
    model.eval()
    return tok, model, revision or getattr(model.config, "_commit_hash", None)


def _eos_ids(tokenizer, model):
    ids = set()
    for source in (getattr(model.generation_config, "eos_token_id", None), tokenizer.eos_token_id):
        if isinstance(source, (list, tuple)):
            ids |= set(source)
        elif source is not None:
            ids.add(source)
    return ids


def generate_batch(tokenizer, model, model_name, prompts, max_new_tokens=None):
    """Decodificação gulosa de um lote. Retorna uma lista de dicts, um por prompt:
    raw_output, prompt_tokens, output_tokens, hit_max_new_tokens, latency_s (do lote / tamanho)."""
    import torch
    max_new_tokens = max_new_tokens or MAX_NEW_TOKENS
    texts = [chat_text(tokenizer, model_name, p) for p in prompts]
    enc = tokenizer(texts, return_tensors="pt", padding=True, add_special_tokens=False)
    n_in = enc["attention_mask"].sum(dim=1).tolist()
    limit = getattr(model.config, "max_position_embeddings", None)
    assert limit is None or max(n_in) + max_new_tokens <= limit, \
        f"prompt de {max(n_in)} tokens não cabe no contexto do modelo ({limit})"
    enc = enc.to(model.device)
    t0 = time.time()
    with torch.inference_mode():
        out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                             temperature=None, top_p=None, top_k=None,
                             pad_token_id=tokenizer.pad_token_id)
    latency = (time.time() - t0) / len(prompts)
    eos = _eos_ids(tokenizer, model)
    results = []
    for n_prompt, row in zip(n_in, out[:, enc["input_ids"].shape[1]:].tolist()):
        n_out = next((i for i, t in enumerate(row) if t in eos), len(row))
        results.append({
            "raw_output": tokenizer.decode(row[:n_out], skip_special_tokens=True).strip(),
            "prompt_tokens": n_prompt,
            "output_tokens": n_out,
            "hit_max_new_tokens": n_out >= max_new_tokens,
            "latency_s": round(latency, 3),
        })
    return results


def _generate_safe(tokenizer, model, model_name, prompts, max_new_tokens):
    """generate_batch com recuo: se faltar memória, divide o lote ao meio e tenta de novo.
    A nova tentativa acontece FORA do `except`: enquanto a exceção está viva, o traceback segura
    os tensores do lote e a memória da GPU não é liberada."""
    import gc
    import torch
    outs = None
    try:
        outs = generate_batch(tokenizer, model, model_name, prompts, max_new_tokens)
    except getattr(torch, "OutOfMemoryError", torch.cuda.OutOfMemoryError):
        if len(prompts) == 1:
            raise
    if outs is not None:
        for o in outs:
            o["batch_size"] = len(prompts)
        return outs
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    mid = len(prompts) // 2
    return (_generate_safe(tokenizer, model, model_name, prompts[:mid], max_new_tokens)
            + _generate_safe(tokenizer, model, model_name, prompts[mid:], max_new_tokens))


def output_flags(raw_output):
    """Sinais de que o modelo continuou escrevendo depois da resposta (medidos no piloto).
    O parser lê o ÚLTIMO "Answer:"; se o modelo inventa uma nova pergunta e a responde,
    a saída tem formato válido mas o número avaliado é o da pergunta inventada."""
    text = str(raw_output or "")
    marks = list(ANSWER_RE.finditer(text))
    after = text[marks[0].end():].split("\n", 1)[1] if marks and "\n" in text[marks[0].end():] else ""
    return {
        "n_answer_marks": len(marks),
        "text_after_answer": bool(after.strip()),
        "new_item_after_answer": bool(re.search(r"question\s*:|report\s*:|===|example \d", after, re.I)),
    }


def make_record(ex, split, model_name, rep, k, gen, context_tokens, precision, phash):
    """Um registro do JSONL (campos da seção 9). `gen` é um item de generate_batch()."""
    res = evaluate(gen["raw_output"], ex["qa"]["exe_ans"])
    return {
        "id": ex["id"], "split": split, "model": model_name, "rep": rep, "code": REP_CODE[rep], "k": k,
        "prompt_tokens": gen["prompt_tokens"], "context_tokens": context_tokens,
        "output_tokens": gen["output_tokens"], "raw_output": gen["raw_output"],
        "parsed_answer": res["pred"], "format_ok": res["format_ok"],
        "correct_strict": res["strict"], "correct_lenient": res["lenient"],
        "error_type": error_type(gen["raw_output"], ex, res),
        "latency_s": gen["latency_s"], "hit_max_new_tokens": gen["hit_max_new_tokens"],
        "batch_size": gen.get("batch_size"), "precision": precision, "prompt_hash": phash,
    }


def read_jsonl(path):
    """Lê um JSONL de resultados. Ignora linha final cortada (sessão caiu no meio da escrita)
    e mantém o primeiro registro de cada id."""
    path = pathlib.Path(path)
    if not path.exists():
        return []
    seen, out = set(), []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec["id"] not in seen:
                seen.add(rec["id"])
                out.append(rec)
    return out


def append_jsonl(path, records):
    import os
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:           # linha final cortada: começa em linha nova
        with open(path, "rb") as f:
            f.seek(-1, 2)
            needs_newline = f.read(1) != b"\n"
    else:
        needs_newline = False
    with open(path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def result_path(results_dir, split, model_name, rep):
    return pathlib.Path(results_dir) / split / f"{model_name}__{rep}.jsonl"


DRIVE_FOLDER = "NLP - Checkpoints"       # pasta do Google Drive onde ficam os resultados (checkpoints)


def drive_results_dir(folder=DRIVE_FOLDER, mount="/content/drive", max_depth=2):
    """Pasta `results/` dentro da pasta `folder` do Google Drive já montado.

    Procura `folder` em "Meu Drive" e nas pastas dele (`max_depth` níveis; atalhos para pastas compartilhadas
    aparecem como pastas). Tudo o que o estudo grava fica aqui, então uma sessão nova do Colab
    continua de onde a anterior parou. Se a pasta não existe, PARA com um erro: criar outra pasta
    em silêncio faria uma segunda conta gravar os resultados no próprio Drive, longe dos demais."""
    root = pathlib.Path(mount) / "MyDrive"
    assert root.is_dir(), f"Google Drive não montado em {mount}"
    level, found = [root], None
    for _ in range(max_depth):
        nxt = []
        for d in level:
            try:
                subdirs = sorted(c for c in d.iterdir() if c.is_dir() and not c.name.startswith("."))
            except OSError:
                continue
            hits = [c for c in subdirs if c.name == folder]
            if hits:
                found = hits[0]
                break
            nxt += subdirs
        if found:
            break
        level = nxt
    if found is None:
        raise FileNotFoundError(
            f"Pasta '{folder}' não encontrada no Google Drive desta conta. Se ela é de outra pessoa, abra o link "
            f"da pasta e use Organizar > Adicionar atalho > Meu Drive; se é sua, crie-a em Meu Drive. Para gravar "
            f"em outro lugar, defina FINRAG_DRIVE_FOLDER (nome da pasta) ou FINRAG_RESULTS_DIR (caminho completo).")
    out = found / "results"
    out.mkdir(parents=True, exist_ok=True)
    return out


def progress(results_dir, split, models, expected):
    """Andamento de um split: perguntas já gravadas por modelo × condição, como DataFrame.
    `expected` é o total por condição: um inteiro ou um dicionário representação -> total."""
    import pandas as pd
    total = expected if isinstance(expected, dict) else {rep: expected for rep in REPRESENTATIONS}
    table = {name: {f"{REP_CODE[rep]} (de {total[rep]})": len(read_jsonl(result_path(results_dir, split, name, rep)))
                    for rep in REPRESENTATIONS} for name in models}
    return pd.DataFrame(table).T


def _progress_bar(total, initial, desc):
    """Barra de progresso (tqdm). Sem tqdm instalado, devolve None e o andamento sai em linhas de texto."""
    try:
        from tqdm.auto import tqdm
    except ImportError:
        return None
    return tqdm(total=total, initial=initial, desc=desc, unit="perg", dynamic_ncols=True, mininterval=2)


def run_condition(tokenizer, model, model_name, examples, rep, shots, out_path, split, precision,
                  k=K_FROZEN, batch_size=4, max_new_tokens=None, log_every=10, save_every=1):
    """Gera as respostas de um modelo em uma condição e grava em JSONL, com retomada.

    Os lotes são definidos pela lista COMPLETA de perguntas, ordenada do prompt mais longo para o
    mais curto; ao retomar, os lotes já gravados são pulados e os outros têm a mesma composição
    de antes. Assim, interromper e retomar não muda os resultados (com o mesmo `batch_size`).
    Recusa continuar um arquivo gravado com outro prompt ou outra precisão.

    `save_every`: grava no arquivo a cada N lotes (1 = a cada lote). Uma queda brusca da sessão perde
    no máximo N lotes; uma interrupção normal (erro ou parada da célula) grava antes de sair. A barra
    de progresso mostra perguntas feitas, ritmo, tempo restante e quantas já estão gravadas."""
    assert save_every >= 1, save_every
    phash = prompt_hash(k)
    previous = read_jsonl(out_path)
    stale = {(r.get("prompt_hash"), r.get("precision")) for r in previous} - {(phash, precision)}
    assert not stale, (f"{out_path} foi gerado com outro prompt ou outra precisão {sorted(stale)}; "
                       f"o atual é {(phash, precision)}. Mova ou apague o arquivo antes de rodar.")
    done = {r["id"] for r in previous}
    items = []
    for ex in examples:
        prompt = build_prompt(ex, rep, shots, k)
        items.append((count_tokens(tokenizer, chat_text(tokenizer, model_name, prompt)), ex["id"], ex, prompt))
    items.sort(key=lambda t: (-t[0], t[1]))
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    todo = [b for b in batches if any(it[1] not in done for it in b)]
    print(f"[{model_name} | {REP_CODE[rep]} {rep} | {split}] {len(done)}/{len(items)} já feitas, "
          f"{len(todo)} lotes a rodar (lote = {batch_size}, gravação a cada {save_every} lote(s))")
    if not todo:
        return previous
    bar = _progress_bar(len(items), len(done), f"{model_name} {REP_CODE[rep]}")
    t0, n_new, n_saved, buffer = time.time(), 0, len(done), []
    try:
        for bi, batch in enumerate(todo, start=1):
            gens = _generate_safe(tokenizer, model, model_name, [it[3] for it in batch], max_new_tokens)
            records = []
            for (n_tok, ex_id, ex, _), gen in zip(batch, gens):
                assert gen["prompt_tokens"] == n_tok, "contagem de tokens do prompt divergiu (truncamento?)"
                if ex_id in done:
                    continue
                ctx_tokens = count_tokens(tokenizer, build_context(ex, rep, k))
                records.append(make_record(ex, split, model_name, rep, k, gen, ctx_tokens, precision, phash))
            buffer += records
            done |= {r["id"] for r in records}
            n_new += len(records)
            if bi % save_every == 0 or bi == len(todo):
                append_jsonl(out_path, buffer)
                n_saved, buffer = n_saved + len(buffer), []
            if bar is not None:
                bar.set_postfix_str(f"gravadas {n_saved}", refresh=False)
                bar.update(len(records))
            elif bi % log_every == 0 or bi == len(todo):
                rate = (time.time() - t0) / max(n_new, 1)
                left = len(items) - len(done)
                print(f"   lote {bi}/{len(todo)} | {rate:.1f} s/pergunta | faltam ~{left * rate / 60:.0f} min | "
                      f"gravadas {n_saved}/{len(items)}")
    finally:
        if buffer:                                   # erro ou parada da célula: grava o que já foi gerado
            append_jsonl(out_path, buffer)
        if bar is not None:
            bar.close()
    return read_jsonl(out_path)


def load_results(results_dir, split):
    """Todos os registros de um split, como DataFrame (um arquivo por modelo × condição)."""
    import pandas as pd
    records = []
    for path in sorted((pathlib.Path(results_dir) / split).glob("*__*.jsonl")):
        records += read_jsonl(path)
    return pd.DataFrame(records)


def git_sha(repo_dir="."):
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def save_json(path, obj):
    """Grava em arquivo temporário e troca no fim: se a sessão cair no meio, o arquivo antigo fica inteiro."""
    import os
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


# =====================================================================================
# 9. Estatística (seção 7.2 da metodologia)
# =====================================================================================
def bootstrap_mean_ci(x, n_boot=10000, seed=0, alpha=0.05):
    """Média com IC por bootstrap (percentil). Retorna (média, inferior, superior)."""
    import numpy as np
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for start in range(0, n_boot, 1000):
        idx = rng.integers(0, len(x), size=(min(1000, n_boot - start), len(x)))
        means[start:start + len(idx)] = x[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(x.mean()), float(lo), float(hi)


def paired_bootstrap(a, b, n_boot=10000, seed=0, alpha=0.05):
    """Diferença de acurácia a − b nas MESMAS perguntas, com IC por bootstrap pareado."""
    import numpy as np
    return bootstrap_mean_ci(np.asarray(a, dtype=float) - np.asarray(b, dtype=float), n_boot, seed, alpha)


def diff_in_diff_bootstrap(d1, d2, n_boot=10000, seed=0, alpha=0.05):
    """Interação (H3): média(d2) − média(d1), em que d1 e d2 são diferenças pareadas (a − b) em dois
    grupos DISJUNTOS de perguntas. Cada grupo é reamostrado separadamente."""
    import numpy as np
    d1, d2 = np.asarray(d1, dtype=float), np.asarray(d2, dtype=float)
    if len(d1) == 0 or len(d2) == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        diffs[i] = (d2[rng.integers(0, len(d2), len(d2))].mean()
                    - d1[rng.integers(0, len(d1), len(d1))].mean())
    lo, hi = np.quantile(diffs, [alpha / 2, 1 - alpha / 2])
    return float(d2.mean() - d1.mean()), float(lo), float(hi)


def ratio_bootstrap(num, den, n_boot=10000, seed=0, alpha=0.05):
    """Razão média(num) / média(den) com IC por bootstrap pareado (as perguntas são reamostradas
    juntas). Usada em Δacurácia / Δtokens; instável quando média(den) é próxima de zero."""
    import numpy as np
    num, den = np.asarray(num, dtype=float), np.asarray(den, dtype=float)
    if len(num) == 0 or den.mean() == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    ratios = np.empty(n_boot)
    for start in range(0, n_boot, 1000):
        idx = rng.integers(0, len(num), size=(min(1000, n_boot - start), len(num)))
        d = den[idx].mean(axis=1)
        ratios[start:start + len(idx)] = np.where(d != 0, num[idx].mean(axis=1) / np.where(d != 0, d, 1), np.nan)
    lo, hi = np.nanquantile(ratios, [alpha / 2, 1 - alpha / 2])
    return float(num.mean() / den.mean()), float(lo), float(hi)


def mcnemar_exact(a, b):
    """Teste de McNemar exato (binomial bilateral) para acertos pareados.
    Retorna (só a acerta, só b acerta, p)."""
    only_a = sum(1 for x, y in zip(a, b) if x and not y)
    only_b = sum(1 for x, y in zip(a, b) if y and not x)
    n = only_a + only_b
    if n == 0:
        return only_a, only_b, 1.0
    tail = sum(math.comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2 ** n
    return only_a, only_b, min(1.0, 2 * tail)


def holm(pvalues):
    """p ajustados pela correção de Holm, na ordem original."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted
