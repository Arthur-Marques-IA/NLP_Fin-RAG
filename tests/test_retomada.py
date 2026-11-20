"""Confere a retomada da geração (checkpoints) sem GPU e sem baixar modelo.

Roda uma condição até o fim; depois repete a mesma condição com interrupções no meio
(a sessão "cai" durante um lote), com a última linha do arquivo cortada (queda no meio da
escrita) e com um arquivo de estado gravado pela metade. O resultado retomado tem de ser
idêntico ao da execução sem interrupção: mesmas perguntas, mesma ordem dentro de cada lote,
mesmas saídas, nenhuma pergunta repetida. Confere também a busca da pasta do Google Drive.

O gerador é falso (a "resposta" é uma função do prompt e do lote) e o tokenizador também.

Uso (na raiz do repositório):  python tests/test_retomada.py [pasta_dos_dados]
"""
import hashlib
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import finrag as F  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class FakeTokenizer:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **kwargs):
        return "<user>" + messages[0]["content"] + "<assistant>"

    def encode(self, text, add_special_tokens=False):
        return text.split()


class SessionDropped(Exception):
    pass


def make_generator(tok, fail_at_call=None):
    """Gerador falso. A saída depende do prompt E da composição do lote, como na geração real com
    padding: se a retomada mudasse os lotes, as saídas mudariam e o teste falharia."""
    state = {"calls": 0}

    def fake(tokenizer, model, model_name, prompts, max_new_tokens):
        state["calls"] += 1
        if fail_at_call is not None and state["calls"] == fail_at_call:
            raise SessionDropped()
        batch_key = hashlib.sha256("\x00".join(prompts).encode("utf-8")).hexdigest()[:8]
        outs = []
        for p in prompts:
            h = int(hashlib.sha256(p.encode("utf-8")).hexdigest()[:6], 16)
            outs.append({"raw_output": f"lote {batch_key}\nAnswer: {h % 1000}.00",
                         "prompt_tokens": F.count_tokens(tok, F.chat_text(tok, model_name, p)),
                         "output_tokens": 5, "hit_max_new_tokens": False, "latency_s": 0.0,
                         "batch_size": len(prompts)})
        return outs
    return fake, state


def comparable(records):
    return [{k: v for k, v in r.items() if k != "latency_s"} for r in records]


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else ROOT / "data"
    train, dev = F.load_finqa("train", data_dir), F.load_finqa("dev", data_dir)
    shots, tok = F.get_fewshot(train), FakeTokenizer()
    examples = dev[:37]                                   # 37 perguntas, lote 4: o último lote é incompleto
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="finrag_retomada_"))
    args = dict(tokenizer=tok, model=None, model_name="falso", examples=examples, rep="markdown", shots=shots,
                split="pilot_dev", precision="cpu-fp32", batch_size=4, log_every=1000)
    try:
        # 1) referência: execução sem interrupção
        F._generate_safe, _ = make_generator(tok)
        ref_path = F.result_path(tmp / "ref", "pilot_dev", "falso", "markdown")
        ref = F.run_condition(out_path=ref_path, **args)
        assert [r["id"] for r in ref] and {r["id"] for r in ref} == {e["id"] for e in examples}

        # 2) três quedas seguidas, em pontos diferentes; depois da segunda, a última linha fica cortada
        path = F.result_path(tmp / "run", "pilot_dev", "falso", "markdown")
        for attempt, fail_at in enumerate((3, 2, 4), start=1):
            F._generate_safe, state = make_generator(tok, fail_at_call=fail_at)
            try:
                F.run_condition(out_path=path, **args)
                raise AssertionError("a queda simulada não aconteceu")
            except SessionDropped:
                pass
            done = len(F.read_jsonl(path))
            print(f"queda {attempt}: sessão caiu no lote {fail_at} desta execução; {done}/{len(examples)} perguntas no arquivo")
            if attempt == 2:
                raw = path.read_bytes()
                path.write_bytes(raw[:-60])              # queda no meio da escrita: última linha incompleta
                print(f"         última linha cortada: {len(F.read_jsonl(path))}/{len(examples)} registros legíveis")
        F._generate_safe, state = make_generator(tok)
        resumed = F.run_condition(out_path=path, **args)

        assert len(resumed) == len(examples), len(resumed)
        assert len({r["id"] for r in resumed}) == len(resumed), "pergunta repetida"
        key = lambda r: r["id"]
        assert sorted(comparable(resumed), key=key) == sorted(comparable(ref), key=key), \
            "a execução retomada difere da execução sem interrupção"
        print(f"retomada: {len(resumed)} registros, sem repetição, idênticos aos da execução sem interrupção "
              f"(a última retomada rodou {state['calls']} lotes dos {-(-len(examples) // 4)})")

        # 2b) gravação a cada 3 lotes: uma interrupção normal grava o que já foi gerado; o fim é o mesmo
        path3 = F.result_path(tmp / "run3", "pilot_dev", "falso", "markdown")
        F._generate_safe, _ = make_generator(tok, fail_at_call=5)
        try:
            F.run_condition(out_path=path3, save_every=3, **args)
            raise AssertionError("a queda simulada não aconteceu")
        except SessionDropped:
            pass
        assert len(F.read_jsonl(path3)) == 16, len(F.read_jsonl(path3))     # 4 lotes completos, todos gravados
        F._generate_safe, _ = make_generator(tok)
        every3 = F.run_condition(out_path=path3, save_every=3, **args)
        assert sorted(comparable(every3), key=key) == sorted(comparable(ref), key=key)
        print("gravação a cada 3 lotes: interrupção grava o que já foi gerado; resultado final idêntico")

        # 3) rodar de novo com tudo pronto não gera nada
        F._generate_safe, state = make_generator(tok)
        F.run_condition(out_path=path, **args)
        assert state["calls"] == 0
        print("condição completa: nada é gerado de novo")

        # 4) andamento e arquivo de estado
        table = F.progress(tmp / "run", "pilot_dev", ["falso"], {rep: 37 for rep in F.REPRESENTATIONS})
        assert table.loc["falso"].tolist() == [0, 37, 0, 0, 0, 0], table
        state_path = tmp / "run" / "frozen_config.json"
        F.save_json(state_path, {"prompt_hash": F.prompt_hash()})
        (state_path.with_name(state_path.name + ".tmp")).write_text('{"prompt_hash": "cort', encoding="utf-8")
        assert F.load_json(state_path) == {"prompt_hash": F.prompt_hash()}   # o temporário cortado não afeta o arquivo
        F.save_json(state_path, {"prompt_hash": "x"})
        assert F.load_json(state_path) == {"prompt_hash": "x"}
        print("andamento e gravação dos arquivos de estado: ok")

        # 5) pasta do Drive: achada por nome (inclusive dentro de outra pasta); se não existe, erro
        mount = tmp / "drive"
        (mount / "MyDrive" / "UFG" / F.DRIVE_FOLDER).mkdir(parents=True)
        found = F.drive_results_dir(mount=mount)
        assert found == mount / "MyDrive" / "UFG" / F.DRIVE_FOLDER / "results" and found.is_dir()
        try:
            F.drive_results_dir("pasta que não existe", mount=mount)
            raise RuntimeError("deveria ter parado: pasta inexistente")
        except FileNotFoundError:
            pass
        assert not (mount / "MyDrive" / "pasta que não existe").exists()
        print("pasta do Drive: encontrada por nome; pasta ausente gera erro, sem criar outra")

        # 6) arquivo gerado com outro prompt é recusado
        old = F.FORMAT_REMINDER
        F.FORMAT_REMINDER = old + " "
        try:
            F.run_condition(out_path=path, **args)
            raise RuntimeError("deveria ter recusado o arquivo de outro prompt")
        except AssertionError:
            print("arquivo gerado com outro prompt: recusado")
        finally:
            F.FORMAT_REMINDER = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nRetomada conferida.")


if __name__ == "__main__":
    main()
