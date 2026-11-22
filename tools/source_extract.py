"""Ekstrakcja źródeł otwartych do lokalnych JSONL (07 §1.2). Wynik NIGDY do Git.

python -m tools.source_extract SRC=PLIK [SRC=PLIK ...] [--out KATALOG] [--exclude LOC ...]
XHTML/EPUB Pressbooks (stdlib) lub PDF (`pdftotext`). Pomija media (iframe/H5P/oEmbed), ryciny, skrypty.
shortcut: wykluczenia z sources.yaml działają po loc (rozdział/strona); ryciny w PDF filtruje tylko `pdftotext`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

MAX_WORDS = 900  # ≈ 1200 tokenów < limit 1500 (07 §1.2 pkt 4)
_SKIP_TAGS = {"script", "style", "iframe", "figure", "img", "svg", "nav", "audio", "video"}
_LIG = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})
_VOID = {"img", "br", "hr", "input", "meta", "link"}


class _Sections(HTMLParser):
    """Dzieli XHTML Pressbooks na sekcje po div#id (front-matter/chapter/back-matter)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.secs: list[tuple[str, list[str]]] = []
        self._skip: list[str] = []   # stos pominiętych elementów
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if self._skip:
            if tag not in _VOID:
                self._skip.append(tag)
            return
        if tag in _SKIP_TAGS or "interactive-content" in cls or "h5p" in cls:
            if tag not in _VOID:
                self._skip.append(tag)
            return
        if tag == "div" and re.match(r"(front-matter|chapter|back-matter)\b", cls) and a.get("id"):
            self.secs.append((a["id"], []))
        elif tag in {"p", "li", "h1", "h2", "h3", "h4", "tr"} and self.secs:
            self.secs[-1][1].append("\n")

    def handle_endtag(self, tag):
        if self._skip and tag not in _VOID:
            self._skip.pop()

    def handle_data(self, data):
        if not self._skip and self.secs:
            self.secs[-1][1].append(data)


def _chunks(text: str) -> list[str]:
    out, cur, n = [], [], 0
    for para in (p.strip() for p in re.split(r"\n\s*\n|\n", text)):
        if not para:
            continue
        w = len(para.split())
        if cur and n + w > MAX_WORDS:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(para)
        n += w
    if cur:
        out.append("\n".join(cur))
    return out


def _read_html(path: Path) -> str:
    if path.suffix == ".epub":
        with zipfile.ZipFile(path) as z:
            return "\n".join(z.read(n).decode("utf8") for n in sorted(z.namelist())
                             if n.endswith((".xhtml", ".html")))
    return path.read_text(encoding="utf8")


def extract_html(path: Path, exclude: list[str]) -> list[dict]:
    p = _Sections()
    p.feed(_read_html(path))
    out = []
    for sid, parts in p.secs:
        for k, ch in enumerate(_chunks("".join(parts)), 1):
            loc = f"{sid}.{k}"
            if not any(loc == x or loc.startswith(x) for x in exclude):
                out.append({"loc": loc, "text": ch})
    return out


def extract_pdf(path: Path, exclude: list[str]) -> list[dict]:
    txt = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True,
                         text=True).stdout.translate(_LIG)
    out = []
    for pg, page in enumerate(txt.split("\f"), 1):
        page = re.sub(r"[ \t]+", " ", page)
        for k, ch in enumerate(_chunks(page), 1):
            loc = f"p{pg}.{k}"
            if not any(loc == x or loc.startswith(x) for x in exclude):
                out.append({"loc": loc, "text": ch})
    return out


def run(src: str, path: Path, out_dir: Path, exclude: list[str]) -> int:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    frs = (extract_pdf if path.suffix == ".pdf" else extract_html)(path, exclude)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{src}.jsonl").open("w", encoding="utf8") as f:
        for fr in frs:
            f.write(json.dumps({"src": src, "sha": sha, **fr}, ensure_ascii=False) + "\n")
    return len(frs)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+", help="id=plik")
    ap.add_argument("--out", type=Path,
                    default=Path.home() / ".local/share/english-ai-tutor/content_sources/extracted")
    ap.add_argument("--exclude", nargs="*", default=[])
    a = ap.parse_args(argv)
    for pr in a.pairs:
        src, _, f = pr.partition("=")
        print(f"{src}: {run(src, Path(f), a.out, a.exclude)} fragmentów")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
