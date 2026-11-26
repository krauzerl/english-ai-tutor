"""Ponowne liczenie metryk z zapisanych wierszy (bez modelu) — po poprawce funkcji oceny, nie po zmianie systemu.

  python -m bench.b_lite_rescore bench/results/b_lite/held_ABCD.json [--set b_lite --split held]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.b_lite import load, score
from tutor.pedagogy.assessment import Classified, UttResult


def results_from_rows(rows: list[dict]) -> list:
    out = []
    for r in rows:
        obs = [Classified("error", "valid", None, s, f, c, 2, conf, source=src) for s, f, c, conf, src in
               r.get("reported", [])]
        out.append(UttResult(0, r["status"], obs))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--set", default="b_lite")
    ap.add_argument("--split", default="held")
    a = ap.parse_args(argv)
    d = json.loads(Path(a.file).read_text())
    cases = load(a.set, a.split)
    for run in d["runs"]:
        res = results_from_rows(run["levels"]["log"]["rows"])     # poziom log zawiera też zgłoszenia h
        run["rescored"] = {lv: score(cases, res, lv) for lv in ("recast", "log")}
        s = {lv: {k: v for k, v in m.items() if k != "rows"} for lv, m in run["rescored"].items()}
        print(json.dumps({"variant": run["variant"], "repeat": run["repeat"], **s}, ensure_ascii=False))
    Path(a.file).write_text(json.dumps(d, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
