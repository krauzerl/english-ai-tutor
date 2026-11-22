"""Generator zadań (04_PEDAGOGY_SPEC §5.3): LLM (rola generation) -> walidator -> zapis WYŁĄCZNIE jako draft.

  python -m tools.gen_items en --skill en.gram.past_simple_regular --type gap --cefr A2 [--n 1]
  python -m tools.gen_items en --solve-check [--only-draft] [--reject-on-mismatch]

Nie robi masowej generacji: --n <= 5. Nie potrafi ustawić reviewer/reviewed_at ani statusu innego niż draft
(ścieżka `set_ai_check` dopuszcza najwyżej ai_checked). `human_reviewed` tylko przez `main.py content review`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from pydantic import BaseModel

from tutor.pedagogy import content as C

MAX_N = 5


class GenItem(BaseModel):
    prompt: str
    options: list[str] | None = None
    answers: list[str]
    explanation_pl: str | None = None
    difficulty: float = 0.0
    stimulus: str | None = None
    audio_text: str | None = None


class Solve(BaseModel):
    answer: str = ""
    multiple_correct: bool = False
    unclear: bool = False


def _fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def next_id(pack: C.Pack, area: str, cefr: str) -> str:
    slug = {"grammar": "gram", "vocabulary": "vocab", "reading": "read", "listening": "listen"}.get(area, area)
    n = 1 + sum(1 for i in pack.items if i.startswith(f"{pack.lang}.gen.{slug}.{cefr.lower()}."))
    return f"{pack.lang}.gen.{slug}.{cefr.lower()}.{n:04d}"


def generate(pack: C.Pack, provider, structured, *, skill_id: str, item_type: str, cefr: str, domain: str,
             model_name: str, today: str) -> tuple[str | None, list[str]]:
    """Zwraca (id zapisanego zadania | None, błędy walidacji). Niezwalidowane zadanie nie trafia na dysk."""
    from tutor.llm.base import Message
    sk = pack.skills[skill_id]
    prompt = _fill(pack.prompts["gen_item"]["text"], skill_id=skill_id, can_do=sk.can_do_pl, cefr=cefr,
                   item_type=item_type, domain=domain)
    g = structured(provider, [Message("user", prompt)], GenItem, temperature=0.4, max_tokens=700)
    item = {"id": next_id(pack, sk.area, cefr), "lang": pack.lang, "skill_ids": [skill_id], "area": sk.area,
            "type": item_type, "cefr": cefr, "difficulty": max(-1.0, min(1.0, g.difficulty)),
            "pools": ["practice"], "domain": domain, "prompt": g.prompt, "stimulus": g.stimulus,
            "options": g.options, "answers": g.answers, "explanation_pl": g.explanation_pl,
            "audio_text": g.audio_text,
            "provenance": {"source": "ai_generated", "model": model_name,
                           "prompt_version": pack.prompts["gen_item"]["version"], "created_at": today}}
    errs = _validate_candidate(pack, item)
    if errs:
        return None, errs
    return C.append_draft(pack, item), []


def _validate_candidate(pack: C.Pack, item: dict) -> list[str]:
    from tutor.pedagogy.content import Item, Report, _check_item
    rep = Report()
    try:
        it = Item.model_validate({**item, "review": {"status": "draft"}})
    except Exception as e:  # pydantic ValidationError
        return [str(e)]
    if any(norm_eq(it, o) for o in pack.items.values()):
        return ["duplikat istniejącego zadania"]
    _check_item(it, pack, rep, "candidate")
    return rep.errors


def norm_eq(a: C.Item, b: C.Item) -> bool:
    k = lambda i: "|".join(C.norm_answer(x or "") for x in (i.prompt, i.stimulus, i.audio_text))  # noqa: E731
    return k(a) == k(b)


def solve_check(pack: C.Pack, provider, structured, item: C.Item, *,
                reject_on_mismatch: bool = False) -> tuple[str, str]:
    """Rozwiązanie na ślepo (bez klucza). Zgodność => ai_checked; inaczej draft z notatką (albo rejected)."""
    from tutor.llm.base import InvalidStructuredOutput, Message
    prompt = _fill(pack.prompts["solve_item"]["text"], item_type=item.type, stimulus=item.stimulus or "-",
                   audio_text=item.audio_text or "-", prompt=item.prompt,
                   options=json.dumps(item.options, ensure_ascii=False) if item.options else "-")
    try:
        s = structured(provider, [Message("user", prompt)], Solve, temperature=0.0, max_tokens=120)
    except InvalidStructuredOutput:
        return "draft", "solve_check: niepoprawna odpowiedź modelu (brak werdyktu)"
    agree = (not s.unclear and not s.multiple_correct and bool(s.answer.strip())
             and C.norm_answer(s.answer) in C.expand_answers(item.answers or [], pack.variants, item.domain))
    if agree:
        return "ai_checked", "solve_check: zgodne z kluczem (kontrola AI na ślepo, nie recenzja człowieka)"
    why = "niejednoznaczne/więcej niż jedna poprawna" if (s.unclear or s.multiple_correct) else "niezgodność z kluczem"
    return ("rejected" if reject_on_mismatch else "draft"), f"solve_check: {why}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gen_items")
    ap.add_argument("lang")
    ap.add_argument("--skill")
    ap.add_argument("--type", dest="item_type", default="gap")
    ap.add_argument("--cefr", default="A2")
    ap.add_argument("--domain", default="general")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--solve-check", action="store_true")
    ap.add_argument("--only-draft", action="store_true", help="solve-check tylko dla zadań w statusie draft")
    ap.add_argument("--reject-on-mismatch", action="store_true")
    a = ap.parse_args(argv)
    if a.n > MAX_N:
        print(f"--n <= {MAX_N}: masowa generacja jest poza zakresem.", file=sys.stderr)
        return 1
    from tutor.llm import build_provider
    from tutor.llm.structured import structured
    pack = C.load(a.lang)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if a.solve_check:
        prov = build_provider("evaluation")
        stats = {"ai_checked": 0, "draft": 0, "rejected": 0}
        for it in list(pack.items.values()):
            if it.review.status == "human_reviewed" or (a.only_draft and it.review.status != "draft") \
                    or it.type in C.OPEN_TYPES:
                continue
            status, note = solve_check(pack, prov, structured, it, reject_on_mismatch=a.reject_on_mismatch)
            C.set_ai_check(pack, it.id, status, note)
            stats[status] += 1
            print(f"{it.id}: {status}  {note}")
        print(stats)
        return 0
    if not a.skill:
        print("--skill wymagany", file=sys.stderr)
        return 1
    prov = build_provider("generation")
    for _ in range(a.n):
        iid, errs = generate(pack, prov, structured, skill_id=a.skill, item_type=a.item_type, cefr=a.cefr,
                             domain=a.domain, model_name=prov.model, today=today)
        print(iid or f"ODRZUCONE: {errs}")
        pack = C.load(a.lang)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
