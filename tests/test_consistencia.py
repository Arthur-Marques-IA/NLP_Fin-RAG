"""Confere que src/finrag.py e o notebook 01 são a mesma coisa.

O notebook 01 explica e verifica as representações e a avaliação; os notebooks 02–04 usam a
cópia em src/finrag.py. Este script executa o código do notebook 01 e compara, em TODAS as
tabelas do dev e do teste:
  - a saída de serialize() e de build_context() nas seis representações;
  - as linhas escolhidas pela seleção e a preservação do gabarito;
  - os metadados (passos, origem da evidência, linhas de dados);
  - a avaliação, nos casos do parser e no campo `answer` dos anotadores.
Depois roda as verificações V1–V6 da metodologia a partir do módulo.

Uso (na raiz do repositório):  python tests/test_consistencia.py [pasta_dos_dados]
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import finrag as F  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Células do notebook 01 que definem o que o módulo copia (pelo primeiro comentário da célula).
WANTED = ("# Metadados por pergunta", "# Serializações da tabela", "# Escolha de k no dev",
          "# Extração e avaliação de respostas")


def notebook_namespace(dev, test):
    nb = json.loads((ROOT / "notebooks" / "01_dados_representacoes.ipynb").read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    ns = {"json": json, "finqa_dev": dev, "finqa_test": test, "print": lambda *a, **k: None}
    for start in WANTED:
        code = next(c for c in cells if c.startswith(start))
        exec(compile(code, start, "exec"), ns)
    return ns


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else ROOT / "data"
    dev, test = F.load_finqa("dev", data_dir), F.load_finqa("test", data_dir)
    nb = notebook_namespace(dev, test)
    k = nb["K"]
    assert k == F.K_FROZEN == F.choose_k(dev)[0], (k, F.K_FROZEN)
    print(f"k escolhido no dev: notebook = módulo = {k}")

    examples = dev + test
    n = 0
    for ex in examples:
        for rep in F.REPRESENTATIONS:
            assert F.serialize(ex, rep, k) == nb["serialize"](ex, rep, k), (ex["id"], rep)
            assert F.build_context(ex, rep, k) == nb["build_context"](ex, rep, k), (ex["id"], rep)
            n += 1
        question = ex["qa"]["question"]
        assert F.select_rows(ex["table"], question, k) == nb["select_rows"](ex["table"], question, k)
        assert F.gold_preserved(ex, k) == nb["gold_preserved"](ex, k)
        assert F.count_steps(ex["qa"]["program"]) == nb["count_steps"](ex["qa"]["program"])
        assert F.evidence_source(ex["qa"]["gold_inds"]) == nb["evidence_source"](ex["qa"]["gold_inds"])
        assert F.evaluate("Answer: " + str(ex["qa"]["answer"]), ex["qa"]["exe_ans"]) == \
            nb["evaluate"]("Answer: " + str(ex["qa"]["answer"]), ex["qa"]["exe_ans"])
    print(f"serialize() e build_context() idênticos em {n} pares (tabela, representação)")

    meta_nb, meta_mod = nb["meta"], F.build_meta(test, k)
    for col in ("id", "n_steps", "steps_main", "steps_bin", "evidence", "n_rows", "effective_h2", "has_gold_rows"):
        assert list(meta_nb[col]) == list(meta_mod[col]), col
    print(f"metadados do teste idênticos ({len(meta_mod)} perguntas; "
          f"subconjunto efetivo da H2 = {int(meta_mod.effective_h2.sum())})")

    assert F.PARSER_TESTS == nb["PARSER_TESTS"]
    for text, gold, *_ in F.PARSER_TESTS:
        assert F.evaluate(text, gold) == nb["evaluate"](text, gold)
    print(f"avaliação idêntica nos {len(F.PARSER_TESTS)} casos do parser e no campo answer de {len(examples)} perguntas")

    for name, value in F.run_checks(examples, k).items():
        print(f"{name}: {value}")
    print("\nTudo consistente.")


if __name__ == "__main__":
    main()
