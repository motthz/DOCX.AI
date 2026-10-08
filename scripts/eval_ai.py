r"""Banco di prova della compilazione AI con un modello vero (llama-server + GGUF).

    python scripts/eval_ai.py --runtime CARTELLA_LLAMA --model MODELLO.gguf [--exe llama-server.exe]
                              [--cases tests/fixtures/eval_cases.json] [--only ID] [--threads N] [--verbose]

Per ogni caso compila lo schema dal testo e confronta i campi con i valori attesi:
- date / numeri / Sì-No / scelte: valore esatto
- testi: devono contenere le parole indicate ("contains"), oppure essere vuoti ("empty")
Stampa il punteggio per caso e totale (campi corretti / campi verificati) e il tempo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", s).strip()


def _is_empty(v) -> bool:
    return v in (None, False, [], {}, "") or (isinstance(v, str) and v.strip().upper() in ("", "NON_SPECIFICATO",
                                                                                         "NON_SPECIFICATO"))


def _resolve_date(expr: str, today: date) -> str:
    """"today", "today-1", "lastwd0" (lunedi' scorso), "2026-10-02" -> AAAA-MM-GG."""
    m = re.fullmatch(r"lastwd(\d)", expr)
    if m:
        return (today - timedelta(days=(today.weekday() - int(m.group(1))) % 7 or 7)).isoformat()
    m = re.fullmatch(r"today([+-]\d+)?", expr)
    if m:
        return (today + timedelta(days=int(m.group(1) or 0))).isoformat()
    return expr


def _as_iso(v) -> str:
    if not isinstance(v, str):
        return str(v)
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", v.strip())
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return v.strip()


def check(expected, got, today: date) -> bool:
    """Un valore atteso puo' essere: valore esatto, {"date": ...}, {"contains": [...]},
    {"empty": true}, {"items": [atteso, ...]} (elenco: ogni atteso deve corrispondere a una voce)."""
    if isinstance(expected, dict):
        if expected.get("empty"):
            return _is_empty(got) or (isinstance(got, list) and all(_is_empty(x) for x in got))
        if "date" in expected:
            return _as_iso(got) == _resolve_date(expected["date"], today)
        if "contains" in expected:
            text = _norm(json.dumps(got, ensure_ascii=False) if not isinstance(got, str) else got)
            return not _is_empty(got) and all(_norm(w) in text for w in expected["contains"])
        if "any" in expected:
            return any(check(e, got, today) for e in expected["any"])
        if "items" in expected:
            if not isinstance(got, list) or len(got) != len(expected["items"]):
                return False
            pool = list(got)
            for exp in expected["items"]:
                hit = next((g for g in pool if check(exp, g, today)), None)
                if hit is None:
                    return False
                pool.remove(hit)
            return True
        if "fields" in expected:
            return isinstance(got, dict) and all(check(e, got.get(k), today) for k, e in expected["fields"].items())
    if isinstance(expected, bool):
        return got is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return abs(float(got) - float(expected)) < 1e-6
        except (TypeError, ValueError):
            return False
    return _norm(got) == _norm(expected)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--exe", default="llama-server.exe")
    ap.add_argument("--src", default=str(ROOT / "src"), help="sorgenti dell'app da provare")
    ap.add_argument("--cases", default=str(ROOT / "tests" / "fixtures" / "eval_cases.json"))
    ap.add_argument("--only", default="")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    sys.path.insert(0, args.src)
    from docx_ai.llm.json_pipeline import JsonPipeline
    from docx_ai.llm.llama_server import LlamaServer, LlamaServerOptions

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    srv = LlamaServer(LlamaServerOptions(runtime_dir=Path(args.runtime), runtime_exe=args.exe,
                                         model_path=Path(args.model), context_size=args.ctx,
                                         thread_override=args.threads or None))
    srv.start()
    today = date.today()
    tot_ok = tot_n = 0
    t_all = time.time()
    try:
        for case in cases:
            schema = case.get("schema")
            if isinstance(schema, str):
                schema = json.loads((ROOT / schema).read_text(encoding="utf-8"))
            pipe = JsonPipeline(srv, max_retries=2)
            t0 = time.time()
            res = pipe.extract(schema, case["text"], document_context=case.get("document", ""))
            dt = time.time() - t0
            data = res.data or {}
            ok = n = 0
            wrong = []
            for key, exp in case["expected"].items():
                n += 1
                if check(exp, data.get(key), today):
                    ok += 1
                else:
                    wrong.append(f"    ✗ {key}: atteso {json.dumps(exp, ensure_ascii=False)} "
                                 f"→ {json.dumps(data.get(key), ensure_ascii=False)}")
            tot_ok += ok
            tot_n += n
            print(f"[{case['id']}] {ok}/{n} campi corretti in {dt:.0f}s")
            for w in wrong:
                print(w)
            if args.verbose:
                for c in res.corrections or []:
                    print("    · " + c)
    finally:
        srv.stop()
    print(f"TOTALE {tot_ok}/{tot_n} = {100 * tot_ok / max(1, tot_n):.1f}% in {time.time() - t_all:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
