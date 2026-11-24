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

from tutor.app import ingest, intent
from tutor.pedagogy import content as C

DEFAULT_SKILL = "en.gram.to_be_present"
N_ITEMS = 3
MAX_INTENT_WORDS = 14  # dłuższa wypowiedź to raczej próba odpowiedzi niż polecenie
MAX_HELP = 3           # tyle razy wyjaśniamy na prośbę ucznia, zanim zadanie liczy się jak zwykle
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
    moved_on: bool = False  # uczeń sam zakończył ćwiczenia (nie oznacza opanowania)
    skipped: int = 0       # zadania bez rozstrzygnięcia (niepewne STT): nie są „zrobione”, wrócą po wznowieniu


def prepare(pack: C.Pack, skill_id: str, n: int = N_ITEMS,
            allow_unreviewed: bool = True) -> tuple[C.Skill, list[C.Item]]:
    sk = pack.skills.get(skill_id)
    if sk is None:
        raise LessonError(f"Nieznany cel lekcji: {skill_id}")
    if not sk.explanation_ref or sk.explanation_ref not in pack.explanations or \
            not (pack.root / sk.explanation_ref).exists():
        raise LessonError(f"Cel {skill_id} nie ma wyjaśnienia — nie da się poprowadzić lekcji.")
    items = [i for i in C.select_items(pack, pool="practice", purpose="practice", skill_id=skill_id,
                             allow_unreviewed_practice=allow_unreviewed)
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


_CONTR = {"i'm": "i am", "you're": "you are", "we're": "we are", "they're": "they are", "he's": "he is",
          "she's": "she is", "it's": "it is", "that's": "that is", "there's": "there is", "isn't": "is not",
          "aren't": "are not", "wasn't": "was not", "weren't": "were not", "don't": "do not", "doesn't": "does not",
          "didn't": "did not", "can't": "can not", "cannot": "can not", "won't": "will not", "i've": "i have",
          "i'll": "i will", "i'd": "i would"}
_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
        "seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _num(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")
    return _ONES[n // 100] + " hundred" + (f" {_num(n % 100)}" if n % 100 else "")


def _prep(text: str) -> str:
    """Whisper pisze „I'm” i cyfry; porównujemy w formie rozwiniętej („i am”, „twenty five”)."""
    t = C.norm_answer(text.replace("’", "'"))
    t = " ".join(_CONTR.get(w, w) for w in t.split())
    return " ".join(_num(int(w)) if w.isdigit() and int(w) < 1000 else w for w in t.split())


def _gap_spans(item: C.Item) -> list[tuple[list[str], int, int]]:
    pre, suf = (_prep(x).split() for x in item.prompt.split("___", 1))
    out = []
    for a in item.answers:
        slot = _prep(a).split()
        out.append((pre + slot + suf, len(pre), len(pre) + len(slot)))
    return out


def check(pack: C.Pack, item: C.Item, text: str) -> bool:
    t = text.strip()
    if item.options:                       # mc: numer 1..n lub litera a..d wskazuje opcję
        if t.isdigit():
            t = item.options[int(t) - 1] if 1 <= int(t) <= len(item.options) else ""
        elif len(t) == 1 and t.lower() in "abcdefgh"[:len(item.options)]:
            t = item.options["abcdefgh".index(t.lower())]
    if not t:
        return False
    p = _prep(t)
    if item.type == "gap" and "___" in item.prompt:    # całe zdanie albo jego fragment z brakującym słowem
        rw = p.split()
        for fw, lo, hi in _gap_spans(item):
            for st in range(0, lo + 1):
                if fw[st:st + len(rw)] == rw and st + len(rw) >= hi:
                    return True
    alt = item.model_copy(update={"answers": [*item.answers, *{_prep(a) for a in item.answers}]})
    return C.answer_ok(alt, t, pack.variants) or C.answer_ok(alt, p, pack.variants)


def _known(pack: C.Pack, skill_id: str) -> set[str]:
    """Formy, które w materiale tej umiejętności są odpowiedziami luk albo odróżniają opcje mc (np. is/are/be).
    Wspólne słowa opcji („they”, „at”, „home”) nie są „formami” — pojedyncze takie słowo to raczej błąd rozpoznania."""
    out: set[str] = set()
    for it in pack.items.values():
        if skill_id not in it.skill_ids:
            continue
        if it.type == "gap":
            out |= {w for a in it.answers or [] for w in _prep(a).split() if len(_prep(a).split()) == 1}
        elif it.options:
            toks = [set(_prep(o).split()) for o in it.options]
            out |= set.union(*toks) - set.intersection(*toks)
    return out


def clear_attempt(pack: C.Pack, skill_id: str, item: C.Item, text: str) -> bool:
    """Czy błędna odpowiedź głosowa to wyraźna próba (błąd ucznia), a nie prawdopodobny błąd rozpoznania?
    Niejasne wypowiedzi (np. „M.”, „Um”) NIE są dopasowywane do oczekiwanej odpowiedzi ani liczone jako błąd."""
    w = _prep(text).split()
    if not w:
        return False
    if item.options:
        t = text.strip()
        return 1 <= int(t) <= len(item.options) if t.isdigit() else \
            _prep(text) in {_prep(o) for o in item.options}
    if item.type == "gap" and "___" in item.prompt:
        frame = {x for part in item.prompt.split("___", 1) for x in _prep(part).split()}
        if len(w) == 1:
            return w[0] in _known(pack, skill_id)
        extra = [x for x in w if x not in frame]
        return len(extra) <= 3 and len(extra) < len(w)
    return len(w) >= 3


def _category(pack: C.Pack, sk: C.Skill):
    ids = set(sk.error_categories)
    return next((c for c in pack.errors.categories if c.id in ids), None)


def _show(item: C.Item, idx: int, n: int) -> str:
    opts = "".join(f"\n  {k}. {o}" for k, o in enumerate(item.options or [], 1))
    return f"\nZadanie {idx + 1}/{n}: {item.prompt}{opts}"


def begin(repo, pack: C.Pack, profile_id: int, session_id: int, skill_id: str,
          choice: dict | None = None, allow_unreviewed: bool = True) -> tuple[C.Skill, list[C.Item]]:
    """Nowa lekcja zapisuje plan w sesji; wznowiona używa zapisanych zadań (te same, w tej samej kolejności)."""
    plan = repo.get_session_plan(profile_id, session_id)
    sk, items = prepare(pack, skill_id, allow_unreviewed=allow_unreviewed)
    if plan.get("lesson") == skill_id:
        by = {i.id: i for i in pack.items.values()}
        saved = [by[x] for x in plan.get("items", []) if x in by]
        return sk, saved or items
    repo.set_session_plan(profile_id, session_id,
                          {"lesson": skill_id, "items": [i.id for i in items], "done": [], "ok": [], "choice": choice})
    return sk, items


def run_exercises(repo, pack: C.Pack, profile_id: int, session_id: int, sk: C.Skill, items: list[C.Item],
                  ask: Callable[[C.Item, int], Answer | None], say: Callable[[str], None], *,
                  now: datetime, speak: Callable[[str], None] | None = None) -> Result:
    """`ask` zwraca None = uczeń kończy (postęp zostaje zapisany; wznowienie pomija zrobione zadania)."""
    plan = repo.get_session_plan(profile_id, session_id) or {"lesson": sk.id, "items": [i.id for i in items]}
    done, ok = list(plan.get("done", [])), list(plan.get("ok", []))
    cat = _category(pack, sk)
    skipped = 0
    from tutor.app import lesson_voice as V
    speak = speak or (lambda _t: None)                     # głos tylko w trybie głosowym; ekran zawsze
    for idx, item in enumerate(items):
        if item.id in done:
            continue
        say(_show(item, idx, len(items)))
        speak(V.task(item, idx, len(items)))
        tries = reasks = helps = 0
        while True:
            a = ask(item, idx)
            if a is None:
                return Result(len(ok), len(done), quit=True)
            if a.mode == "voice":                          # uczeń widzi, co usłyszał system (tylko na ekranie)
                say(_heard(a))
            if check(pack, item, a.text):
                say("✓ Dobrze." + (" (po podpowiedzi)" if tries else "")
                    + (f" {item.explanation_pl}" if item.explanation_pl else ""))
                speak(V.correct(tries))
                _record(repo, pack, profile_id, session_id, sk, item, True, a, tries, now)
                ok.append(item.id)
                break
            # jasny sygnał ucznia (krótka wypowiedź); nigdy nie oznacza opanowania
            sig = intent.detect(a.text) if len(a.text.split()) <= MAX_INTENT_WORDS else None
            if sig == "skip":
                say("Dobrze, kończymy ćwiczenia. To nie oznacza opanowania umiejętności — nic nie zapisano jako "
                    "zrobione. Do zadań wrócisz poleceniem `--lesson`.")
                speak(V.stop_exercises())
                return Result(len(ok), len(done), moved_on=True, skipped=skipped)
            if sig == "help" and helps < MAX_HELP:
                helps += 1
                ex = _examples(pack, sk)
                say("Przypomnienie — poprawne przykłady: " + "; ".join(ex) if ex else "Przypomnienie: " + sk.can_do_pl)
                speak(V.help_(ex))
                say(_show(item, idx, len(items)))
                speak(V.task(item, idx, len(items)))
                continue
            heard = set(C.norm_answer(a.text).split())
            unsure = a.mode == "voice" and (a.low_probs is None or bool(heard & set(a.low_probs)))
            if a.mode == "voice" and (unsure or not clear_attempt(pack, sk.id, item, a.text)):
                # niska pewność STT albo niejasna wypowiedź nie jest dowodem błędu językowego i nie jest dopasowywana
                reasks += 1
                if reasks > MAX_REASK:
                    say("Pomijam to zadanie: rozpoznawanie mowy jest niepewne. Wpisz odpowiedź albo wróć do niego "
                        "po wznowieniu lekcji.")
                    speak(V.skipped())
                    skipped += 1
                    item = None
                    break
                say(f"Nie jestem pewien, czy dobrze usłyszałem („{a.text}”). Powiedz jeszcze raz albo wpisz odpowiedź.")
                speak(V.reask(a.text))
                continue
            tries += 1
            if tries == 1:
                say((cat.l1 if cat else "Prawie!") + " Spróbuj jeszcze raz.")
                speak(V.retry())
                continue
            say(f"Poprawna odpowiedź: {item.answers[0]}" + (f"\n{item.explanation_pl}" if item.explanation_pl else ""))
            speak(V.reveal(item))
            _record(repo, pack, profile_id, session_id, sk, item, False, a, 4, now)
            break
        if item is None:                                   # pominięte: zostaje do zrobienia
            continue
        done.append(item.id)
        repo.set_session_plan(profile_id, session_id, {**plan, "done": done, "ok": ok})
    return Result(len(ok), len(done), skipped=skipped)


def _record(repo, pack, pid, sid, sk, item, correct, a: Answer, hint_level, now) -> None:
    ingest.apply_item_attempt(repo, pack, pid, sid, item.id, sk.id, correct, source="practice",
                              dedupe_key=f"lesson:{sid}:{item.id}", now=now, response=a.text,
                              hint_level=hint_level, n_options=len(item.options) if item.options else None,
                              allow_mastery=False)


def _heard(a: Answer) -> str:
    low = f" (niepewne słowa: {', '.join(a.low_probs)})" if a.low_probs else \
        " (brak danych o pewności rozpoznania)" if a.low_probs is None else ""
    return f"  Usłyszałem: „{a.text}”{low}"


def summary(res: Result) -> str:
    if res.moved_on:
        return ("\nĆwiczenia zakończone na Twoją prośbę. To nie oznacza opanowania umiejętności — "
                "opanowanie wymaga potwierdzenia w ćwiczeniach.")
    if res.skipped:
        return (f"\nPominięto {res.skipped} zadań z powodu niepewnego rozpoznania mowy — wrócą po wznowieniu lekcji "
                f"(to samo polecenie `--lesson`). Rozwiązane: {res.correct}/{res.total}.")
    return (f"\nWynik ćwiczeń: {res.correct}/{res.total} poprawnie. To wynik ćwiczeń, który nie oznacza opanowania "
            "umiejętności — opanowanie wymaga potwierdzenia w kolejnych dniach.")


def intro(pack: C.Pack, sk: C.Skill, choice: dict | None = None) -> str:
    why = f"Dlaczego ten cel: {choice['reason']}\n\n" if choice else ""
    return (f"Cel lekcji: {sk.id} ({sk.cefr}) — {sk.can_do_pl}\n{why}\n{explanation(pack, sk)}\n\n"
            "Ćwiczenia: odpowiadaj tekstem lub głosem (q = przerwij, lekcję można wznowić).")


def _examples(pack: C.Pack, sk: C.Skill, n: int = 3) -> list[str]:
    _, body = C._split_front((pack.root / sk.explanation_ref).read_text(encoding="utf-8"))
    m = re.search(r"^## Poprawnie\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    return [ln[2:].strip() for ln in (m.group(1).splitlines() if m else []) if ln.startswith("- ")][:n]


def system_focus(pack: C.Pack, sk: C.Skill) -> str:
    ex = "; ".join(_examples(pack, sk))
    return (f" Lesson focus: the student has just practised '{sk.id}' ({sk.can_do_pl}). Target forms, e.g.: {ex}. "
            "Ask questions whose natural answers need these forms, one question per turn. Do not quiz them, "
            "do not ask whether they feel ready or confident, do not announce the lesson and do not explain the "
            "rule unless asked.")
