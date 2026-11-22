"""Dzielenie strumienia LLM na zdania do syntezy i czyszczenie tekstu pod mowę."""
import re

ABBR = {"mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "sr", "jr", "e.g", "i.e"}
_END = re.compile(r"[.!?…]+[\"')\]]*\s")
_CLAUSE = re.compile(r"[,;:—–]\s")
_JUNK = re.compile(r"[*_#`~>|\[\]{}]|[\U0001F000-\U0001FFFF☀-➿️]")


def clean_for_speech(text: str) -> str:
    """Usuwa markdown/emoji; pusty wynik (bez liter i cyfr) = nic do powiedzenia."""
    t = re.sub(r"^\s*(?:[-•]|\d+[.)])\s+", "", _JUNK.sub("", text), flags=re.M)
    t = re.sub(r"\s+", " ", t).strip()
    return t if re.search(r"\w", t) else ""


class SentenceSplitter:
    """Zwraca zdanie dopiero po znaku końca + spacji (nie tnie „3.5”, „Dr. Smith”).

    Pierwszy fragment może skończyć się na przecinku, gdy ma ≥ first_clause znaków:
    szybszy start mowy kosztem krótszej pierwszej frazy.
    """

    def __init__(self, min_chars: int = 8, first_clause: int = 40):
        self.buf, self.min_chars, self.first_clause, self._first = "", min_chars, first_clause, True

    def _cut(self) -> int | None:
        end = None
        for m in _END.finditer(self.buf):
            head = self.buf[: m.start()].split()
            last = head[-1].lower().rstrip(".") if head else ""
            if m.group().startswith(".") and (last in ABBR or (len(last) == 1 and last.isalpha())):
                continue
            if m.end() >= self.min_chars:
                end = m.end()
                break
        if self._first:
            for m in _CLAUSE.finditer(self.buf):
                if m.end() >= self.first_clause:
                    return m.end() if end is None else min(end, m.end())
        return end

    def feed(self, chunk: str) -> list[str]:
        self.buf += chunk
        out = []
        while (i := self._cut()) is not None:
            out.append(self.buf[:i].strip())
            self.buf, self._first = self.buf[i:], False
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []
