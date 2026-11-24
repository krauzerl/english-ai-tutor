"""Pierwsza kompletna lekcja (F5.8): cel → wyjaśnienie → ćwiczenia → informacja zwrotna → zapis.

Wyłącznie istniejące elementy: umiejętność i zadania z paczki treści, `answer_ok`, drabina podpowiedzi
(`ErrorCategory.l1`), `ingest.apply_item_attempt` (próba `practice`, idempotentna). Brak nowego modelu oceny:
zadania zamknięte sprawdza kod. Wynik ćwiczeń NIE oznacza opanowania (`mastered` wymaga reguł silnika, min. 2 dni).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from tutor.app import ingest
from tutor.pedagogy import content as C

DEFAULT_SKILL = "en.gram.to_be_present"
N_ITEMS = 3
MAX_REASK = 2          # tyle razy prosimy o powtórzenie niepewnie rozpoznanej odpowiedzi głosowej


class LessonError(Exception):
    pass


@dataclass(frozen=True)
class Answer:
    text: str
    mode: str = "text"                 # text | voice
    low_probs: list[str] | None = None  # None = brak danych STT (nie traktujemy odpowiedzi jak pewnej)


@dataclass
class Result:
    correct: int = 0
    total: int = 0
    quit: bool = False


def prepare(pack: C.Pack, skill_id: str, n: int = N_ITEMS) -> tuple[C.Skill, list[C.Item]]:
    sk = pack.skills.get(skill_id)
    if sk is None:
        raise LessonError(f"Nieznany cel lekcji: {skill_id}")
    if not sk.explanation_ref or sk.explanation_ref not in pack.explanations or \
            not (pack.root / sk.explanation_ref).exists():
        raise LessonError(f"Cel {skill_id} nie ma wyjaśnienia — nie da się poprowadzić lekcji.")
    items = [i for i in C.select_items(pack, pool="practice", purpose="practice", skill_id=skill_id)
             if i.type not in C.OPEN_TYPES and i.answers]
    items.sort(key=lambda i: (i.difficulty, i.id))
    if not items:
        raise LessonError(f"Cel {skill_id} nie ma zadań zamkniętych do ćwiczeń.")
    return sk, items[:n]


def explanation(pack: C.Pack, sk: C.Skill) -> str:
    _, body = C._split_front((pack.root / sk.explanation_ref).read_text(encoding="utf-8"))
    body = re.split(r"^## Źródła\s*$", body, maxsplit=1, flags=re.M)[0].strip()
    ex = pack.explanations[sk.explanation_ref]
    if ex.review.status != "human_reviewed":
        body += ("\n\n(Uwaga: wyjaśnienie i zadania nie zostały zrecenzowane przez człowieka — "
                 f"status: {ex.review.status}.)")
    return body


def check(pack: C.Pack, item: C.Item, text: str) -> bool:
    t = text.strip()
    if item.options:                       # mc: numer 1..n lub litera a..d wskazuje opcję
        if t.isdigit():
            t = item.options[int(t) - 1] if 1 <= int(t) <= len(item.options) else ""
        elif len(t) == 1 and t.lower() in "abcdefgh"[:len(item.options)]:
            t = item.options["abcdefgh".index(t.lower())]
    return bool(t) and C.answer_ok(item, t, pack.variants)


def _category(pack: C.Pack, sk: C.Skill):
    ids = set(sk.error_categories)
    return next((c for c in pack.errors.categories if c.id in ids), None)


def _show(item: C.Item, idx: int, n: int) -> str:
    opts = "".join(f"\n  {k}. {o}" for k, o in enumerate(item.options or [], 1))
    return f"\nZadanie {idx + 1}/{n}: {item.prompt}{opts}"


def begin(repo, pack: C.Pack, profile_id: int, session_id: int, skill_id: str) -> tuple[C.Skill, list[C.Item]]:
    """Nowa lekcja zapisuje plan w sesji; wznowiona używa zapisanych zadań (te same, w tej samej kolejności)."""
    plan = repo.get_session_plan(profile_id, session_id)
    sk, items = prepare(pack, skill_id)
    if plan.get("lesson") == skill_id:
        by = {i.id: i for i in pack.items.values()}
        saved = [by[x] for x in plan.get("items", []) if x in by]
        return sk, saved or items
    repo.set_session_plan(profile_id, session_id,
                          {"lesson": skill_id, "items": [i.id for i in items], "done": [], "ok": []})
    return sk, items


def run_exercises(repo, pack: C.Pack, profile_id: int, session_id: int, sk: C.Skill, items: list[C.Item],
                  ask: Callable[[C.Item, int], Answer | None], say: Callable[[str], None], *,
                  now: datetime) -> Result:
    """`ask` zwraca None = uczeń kończy (postęp zostaje zapisany; wznowienie pomija zrobione zadania)."""
    plan = repo.get_session_plan(profile_id, session_id) or {"lesson": sk.id, "items": [i.id for i in items]}
    done, ok = list(plan.get("done", [])), list(plan.get("ok", []))
    cat = _category(pack, sk)
    for idx, item in enumerate(items):
        if item.id in done:
            continue
        say(_show(item, idx, len(items)))
        tries = reasks = 0
        while True:
            a = ask(item, idx)
            if a is None:
                return Result(len(ok), len(done), quit=True)
            if check(pack, item, a.text):
                say("✓ Dobrze." + (" (po podpowiedzi)" if tries else "")
                    + (f" {item.explanation_pl}" if item.explanation_pl else ""))
                _record(repo, pack, profile_id, session_id, sk, item, True, a, tries, now)
                ok.append(item.id)
                break
            heard = set(C.norm_answer(a.text).split())
            if a.mode == "voice" and (a.low_probs is None or heard & set(a.low_probs)):
                # niska pewność STT (lub brak danych) nie jest dowodem błędu językowego
                reasks += 1
                if reasks > MAX_REASK:
                    say("Pomijam to zadanie: rozpoznawanie mowy jest niepewne. Wpisz odpowiedź następnym razem.")
                    break
                say(f"Nie jestem pewien, czy dobrze usłyszałem („{a.text}”). Powiedz jeszcze raz albo wpisz odpowiedź.")
                continue
            tries += 1
            if tries == 1:
                say((cat.l1 if cat else "Prawie!") + " Spróbuj jeszcze raz.")
                continue
            say(f"Poprawna odpowiedź: {item.answers[0]}" + (f"\n{item.explanation_pl}" if item.explanation_pl else ""))
            _record(repo, pack, profile_id, session_id, sk, item, False, a, 4, now)
            break
        done.append(item.id)
        repo.set_session_plan(profile_id, session_id, {**plan, "done": done, "ok": ok})
    return Result(len(ok), len(done))


def _record(repo, pack, pid, sid, sk, item, correct, a: Answer, hint_level, now) -> None:
    ingest.apply_item_attempt(repo, pack, pid, sid, item.id, sk.id, correct, source="practice",
                              dedupe_key=f"lesson:{sid}:{item.id}", now=now, response=a.text,
                              hint_level=hint_level, n_options=len(item.options) if item.options else None,
                              allow_mastery=False)


def summary(res: Result) -> str:
    return (f"\nWynik ćwiczeń: {res.correct}/{res.total} poprawnie. To wynik ćwiczeń, który nie oznacza opanowania "
            "umiejętności — opanowanie wymaga potwierdzenia w kolejnych dniach.")


def intro(pack: C.Pack, sk: C.Skill) -> str:
    return (f"Cel lekcji: {sk.id} ({sk.cefr}) — {sk.can_do_pl}\n\n{explanation(pack, sk)}\n\n"
            "Ćwiczenia: odpowiadaj tekstem lub głosem (q = przerwij, lekcję można wznowić).")


def system_focus(sk: C.Skill) -> str:
    return (f" Lesson focus: the student has just practised '{sk.id}' ({sk.can_do_pl}). Steer the chat so that "
            "they naturally need this structure; do not quiz them and do not announce the lesson.")
