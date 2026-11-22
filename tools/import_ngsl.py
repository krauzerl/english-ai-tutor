"""Import NGSL 1.2 (+ NGSL-Spoken) → tutor/content/en/vocab/ngsl.csv (07 §3.1). Deterministyczny, bez LLM.

python -m tools.import_ngsl [KATALOG_WEJŚCIOWY] [-o PLIK]
Rangi tylko z NGSL_12_stats.csv (nigdy z kolejności wierszy). `cefr` i `gloss_pl` zawsze puste.
XLSX przez stdlib (zipfile + xml.etree), bez openpyxl.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tutor.pedagogy.vocab import variants_of

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HOMOGRAPHS = {"found", "left", "mine", "rose", "wound"}   # z nagłówka teaching CSV
COLUMNS = ["lemma", "forms", "variants", "definition_en", "homograph", "rank", "freq_band", "spoken",
           "spoken_rank", "cefr", "gloss_pl"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_teaching(p: Path) -> list[list[str]]:
    rows = []
    for ln in p.read_text(encoding="utf8").splitlines():
        if ln.startswith("##") or not ln.strip():
            continue
        parts = [x.strip().lower() for x in ln.split(",") if x.strip()]
        rows.append(parts)
    return rows


def read_xlsx_definitions(p: Path) -> dict[str, str]:
    z = zipfile.ZipFile(p)
    ss = [("".join(t.text or "" for t in si.iter(f"{NS}t")))
          for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{NS}si")]
    out: dict[str, str] = {}
    for r in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{NS}row"):
        cells = {}
        for c in r.findall(f"{NS}c"):
            v = c.find(f"{NS}v")
            if v is not None:
                cells[re.match(r"[A-Z]+", c.get("r")).group()] = ss[int(v.text)] if c.get("t") == "s" else v.text
        if cells.get("A") and cells.get("B") and cells["A"] != "Word":
            out[cells["A"].strip().lower()] = cells["B"].strip()
    return out


def read_stats(p: Path | None) -> dict[str, int]:
    if p is None or not p.exists():
        return {}
    with p.open(encoding="utf8", newline="") as f:
        return {r["Lemma"].strip().lower(): int(v) for r in csv.DictReader(f)
                if (v := r.get("SFI Rank") or r.get("Rank") or "").strip().isdigit()}


def band(rank: int | None) -> int | None:
    return None if rank is None else 1 if rank <= 500 else 2 if rank <= 1000 else 3 if rank <= 2000 else 4


def build(teaching: Path, xlsx: Path, stats: Path | None = None, spoken: Path | None = None,
          spoken_stats: Path | None = None) -> list[dict]:
    rows = read_teaching(teaching)
    defs, rank = read_xlsx_definitions(xlsx), read_stats(stats)
    sp = {r[0] for r in read_teaching(spoken)} if spoken and spoken.exists() else None
    sp_rank = read_stats(spoken_stats)
    lemmas = {r[0] for r in rows}
    out = []
    for r in rows:
        lem, forms = r[0], list(dict.fromkeys(r))
        others = lemmas - {lem}
        homo = lem in HOMOGRAPHS or any(f in others for f in forms[1:]) or \
            any(lem in rr[1:] for rr in rows if rr[0] != lem)
        rk = rank.get(lem)
        out.append({"lemma": lem, "forms": "|".join(forms),
                    "variants": ";".join(f"{a}|{b}" for a, b in variants_of(forms)),
                    "definition_en": defs.get(lem, ""), "homograph": "1" if homo else "0",
                    "rank": "" if rk is None else rk, "freq_band": "" if rk is None else band(rk),
                    "spoken": "" if sp is None else int(lem in sp),
                    "spoken_rank": sp_rank.get(lem, ""), "cefr": "", "gloss_pl": ""})
    return sorted(out, key=lambda d: d["lemma"])


def write(rows: list[dict], out: Path, shas: dict[str, str]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf8", newline="") as f:
        f.write("# NGSL 1.2 / NGSL-Spoken 1.2 — Browne, Culligan, Phillips (Spoken: Browne, Culligan). "
                "newgeneralservicelist.com. Licencja CC BY-SA 4.0. Zmodyfikowano: złożone w jeden plik, "
                "dodane warianty BrE/AmE i flagi.\n")
        f.write("# SHA-256 wejść: " + "; ".join(f"{k}={v[:12]}" for k, v in shas.items()) + "\n")
        w = csv.DictWriter(f, COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", type=Path,
                    default=Path.home() / ".local/share/english-ai-tutor/content_sources/vocabulary")
    ap.add_argument("-o", "--out", type=Path, default=Path(__file__).resolve().parent.parent
                    / "tutor/content/en/vocab/ngsl.csv")
    a = ap.parse_args(argv)
    s = a.src
    files = {"teaching": s / "NGSL_1.2_lemmatized_for_teaching.csv",
             "defs": s / "NGSL_1.2_with_English_definitions.xlsx", "stats": s / "NGSL_12_stats.csv",
             "spoken": s / "NGSL-Spoken_12_lemmatized_for_teaching.csv",
             "spoken_stats": s / "NGSL-Spoken_12_stats.csv"}
    rows = build(files["teaching"], files["defs"], files["stats"], files["spoken"], files["spoken_stats"])
    write(rows, a.out, {k: sha(p) for k, p in files.items() if p.exists()})
    print(f"{len(rows)} lematów → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
