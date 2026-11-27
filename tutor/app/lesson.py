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
_EASY = re.compile(r"\b(easy|basic|already know|know this|too simple|simple)\b", re.I)
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
    declared_easy: bool = False  # uczeń napisał, że to łatwe/znane: niepotwierdzone, bez wpływu na mastery
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
    items.sort(key=lambda i: ("diagnosis" in i.pools, i.difficulty, i.id))   # najpierw zadania spoza diagnozy
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


_LETTERS = {"a": 0, "ay": 0, "b": 1, "be": 1, "bee": 1, "c": 2, "see": 2, "sea": 2, "d": 3, "dee": 3}
_ORDINAL = {"one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3, "four": 4, "fourth": 4}
_CHOICE_WRAP = re.compile(r"^(?:(?:it's|it is|the answer is|answer|option|letter|number|i think|i choose)\s+)*"
                          r"(?:the\s+)?(.+?)(?:\s+one)?(?:\s+please)?$")


def _choice(options: list[str], text: str) -> str:
    """Wybór opcji mc z tego, co uczeń wpisał lub powiedział (Whisper: „option B.”, „Number 2”, „the second one”).
    Dosłowna treść opcji wygrywa (opcja „be” ≠ litera B); niejasne słowo zostaje bez zmian (ocena: unclear/wrong)."""
    raw = re.sub(r"[^\w' ]", " ", text.replace("’", "'").lower())
    raw = " ".join(raw.split())
    if raw in {C.norm_answer(o) for o in options}:
        return text.strip()
    core = _CHOICE_WRAP.match(raw).group(1) if raw else ""
    n = int(core) if core.isdigit() else _ORDINAL.get(core)
    if n is None and core in _LETTERS:
        n = _LETTERS[core] + 1
    return options[n - 1] if n and 1 <= n <= len(options) else text.strip()


def check(pack: C.Pack, item: C.Item, text: str) -> bool:
    t = text.strip()
    if item.options:                       # mc: numer 1..n lub litera a..d wskazuje opcję
        t = _choice(item.options, t)
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
    """Nowa lekcja zapisuje plan w sesji; wznowiona używa zapisanych zadań (te same, w tej samej kolejności).
    Lekcja z powtarzającego się błędu (`choice.source == "error"`) jest etapowa: sprawdzenie → wyjaśnienie →
    ćwiczenia → test samodzielny; `transfer` = same nowe zadania po przerwie (bez wyjaśnienia)."""
    plan = repo.get_session_plan(profile_id, session_id)
    sk, items = prepare(pack, skill_id, allow_unreviewed=allow_unreviewed)
    if plan.get("lesson") == skill_id:
        by = {i.id: i for i in pack.items.values()}
        saved = [by[x] for x in plan.get("items", []) if x in by]
        return sk, saved or items
    src, cat = (choice or {}).get("source"), (choice or {}).get("category")
    if src in ("error", "transfer") and cat:
        from tutor.app import remediation as R
        seen = R.seen_items(repo, profile_id, skill_id)
        if src == "error":
            stages = R.staged(pack, skill_id, seen, allow_unreviewed)
            other = None
        else:
            prev = [r for r in R.history(repo, profile_id).get(cat, []) if r["kind"] == "lesson"]
            dom = set(prev[-1]["domains"]) if prev else set()
            stages = {"transfer": R.fresh_items(pack, skill_id, seen, allow_unreviewed, dom)}
            other = bool(stages["transfer"]) and all(i.domain not in dom for i in stages["transfer"])
        checks = [i for st in R.CHECK_STAGES for i in stages.get(st, [])]
        if any(stages.values()):
            cyc = {"category": cat, "skill_id": skill_id, "kind": "lesson" if src == "error" else "transfer",
                   "unverified_items": any(i.review.status != "human_reviewed" for i in checks),
                   "fresh": all(i.id not in seen for i in checks), "other_context": other}
            p = {"lesson": skill_id, **R.plan_for(stages, cyc), "choice": choice}
            repo.set_session_plan(profile_id, session_id, p)
            by = {i.id: i for i in pack.items.values()}
            return sk, [by[x] for x in p["items"]]
    repo.set_session_plan(profile_id, session_id,
                          {"lesson": skill_id, "items": [i.id for i in items], "done": [], "ok": [], "choice": choice})
    return sk, items


_SKIP_CHECK = {"skip", "pomiń", "pomin", "dalej", "skip it"}
STAGE_HEAD = {
    "pre": "Najpierw krótkie sprawdzenie (zadania: {n}), bez podpowiedzi. Reguła i odpowiedzi będą po sprawdzeniu.",
    "practice": "Ćwiczenia (z podpowiedziami, jeśli będą potrzebne).",
    "post": "Teraz samodzielny test na nowych zadaniach (zadania: {n}), bez podpowiedzi.",
    "transfer": "Sprawdzenie po przerwie na nowych zadaniach (zadania: {n}), bez podpowiedzi i bez wyjaśnienia.",
    "check": "Krótkie sprawdzenie głosowe (zadania: {n}), bez podpowiedzi (powiedz „skip”, żeby od razu rozmawiać).",
}


def run_exercises(repo, pack: C.Pack, profile_id: int, session_id: int, sk: C.Skill, items: list[C.Item],
                  ask: Callable[[C.Item, int], Answer | None], say: Callable[[str], None], *,
                  now: datetime, speak: Callable[[str], None] | None = None) -> Result:
    """`ask` zwraca None = uczeń kończy (postęp zostaje zapisany; wznowienie pomija zrobione zadania)."""
    plan = repo.get_session_plan(profile_id, session_id) or {"lesson": sk.id, "items": [i.id for i in items]}
    done, ok = list(plan.get("done", [])), list(plan.get("ok", []))
    stages = plan.get("stages") or {}
    results = dict(plan.get("results") or {})
    req = _check_request(sk, items, plan) if stages else None
    agv = None if stages else _agv_request(pack, sk, items, plan)   # dawny plan: AGV po wyjaśnieniu
    cat = _category(pack, sk)
    skipped = 0
    first: dict[str, bool] = {}
    shown: set[str] = set()
    from tutor.app import lesson_voice as V
    speak = speak or (lambda _t: None)                     # głos tylko w trybie głosowym; ekran zawsze
    for idx, item in enumerate(items):
        if item.id in done:
            continue
        stage = stages.get(item.id)
        if stage and stage not in shown:
            shown.add(stage)
            n_st = sum(1 for i in items if stages.get(i.id) == stage)
            if stage == "practice":
                say("\n" + explanation(pack, sk))
                for part in V.explanation(pack, sk):
                    speak(part)
            say("\n" + STAGE_HEAD[stage].format(n=n_st))
        check = stage in ("pre", "post", "transfer", "check")
        say(_show(item, idx, len(items)))
        speak(V.task(item, idx, len(items)))
        tries = reasks = helps = 0
        res_item = None
        while True:
            a = ask(item, idx)
            if a is None:
                return Result(len(ok), len(done), quit=True)
            if a.mode == "voice":                          # uczeń widzi, co usłyszał system (tylko na ekranie)
                say(_heard(a))
            verdict = judge(pack, sk.id, item, a)
            if stage == "check" and C.norm_answer(a.text) in _SKIP_CHECK:
                verdict = "skip"                           # nagłówek mówi „skip”: jedno słowo wystarcza
            if verdict == "correct":
                res_item = "assisted" if (tries or helps) else "independent"
                if stage == "pre":
                    say("Zapisano odpowiedź.")
                else:
                    say("✓ Dobrze." + (" (po podpowiedzi)" if tries or (check and helps) else "")
                        + (f" {item.explanation_pl}" if item.explanation_pl else ""))
                    speak(V.correct(tries))
                if check:
                    _record_check(repo, pack, profile_id, session_id, req, stage, item, True, a, int(bool(helps)),
                                  now)
                else:
                    _record(repo, pack, profile_id, session_id, sk, item, True, a, tries, now, agv)
                ok.append(item.id)
                first[item.id] = tries == 0
                break
            if verdict == "finish":                       # koniec sesji: jak `q` (postęp zapisany, lekcja wznawialna)
                say("Dobrze, kończymy na dziś. Lekcję możesz wznowić później.")
                return Result(len(ok), len(done), quit=True)
            if verdict == "skip":
                say("Dobrze, kończymy ćwiczenia. To nie oznacza opanowania umiejętności — nic nie zapisano jako "
                    "zrobione. Do zadań wrócisz poleceniem `--lesson`." if stage != "check" else
                    "Dobrze, pomijamy sprawdzenie.")
                speak(V.stop_exercises())
                return Result(len(ok), len(done), moved_on=True, skipped=skipped,
                              declared_easy=bool(_EASY.search(a.text)))
            if verdict == "help" and helps < MAX_HELP:
                helps += 1
                if stage == "pre":                         # podpowiedź zmieniłaby wynik sprawdzenia
                    say("W sprawdzeniu nie podpowiadam — odpowiedz, jak umiesz, albo powiedz „I don't know”. "
                        "Wyjaśnienie będzie zaraz potem.")
                    speak("Just try your best, or say: I don't know.")
                    continue
                ex = _examples(pack, sk)
                say("Przypomnienie — poprawne przykłady: " + "; ".join(ex) if ex else "Przypomnienie: " + sk.can_do_pl)
                speak(V.help_(ex))
                say(_show(item, idx, len(items)))
                speak(V.task(item, idx, len(items)))
                continue
            if verdict == "unclear":
                # niska pewność STT albo niejasna wypowiedź nie jest dowodem błędu językowego i nie jest dopasowywana
                reasks += 1
                if reasks > MAX_REASK:
                    if check:                              # zadanie kontrolne: wynik niejednoznaczny, bez oceny
                        say("Nie mogę wiarygodnie ocenić tej odpowiedzi (niepewne rozpoznanie mowy) — zapisuję ją "
                            "jako niejednoznaczną, bez wpływu na wynik.")
                        res_item = "ambiguous"
                        break
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
            if check:                                      # jedna próba: bez drabiny podpowiedzi
                res_item = "wrong"
                if stage == "pre":
                    say("Zapisano odpowiedź.")
                else:
                    say(f"✗ Poprawna odpowiedź: {item.answers[0]}"
                        + (f"\n{item.explanation_pl}" if item.explanation_pl else ""))
                    speak(V.reveal(item))
                _record_check(repo, pack, profile_id, session_id, req, stage, item, False, a, int(bool(helps)), now)
                break
            if tries == 1:
                say((cat.l1 if cat else "Prawie!") + " Spróbuj jeszcze raz.")
                speak(V.retry())
                continue
            say(f"Poprawna odpowiedź: {item.answers[0]}" + (f"\n{item.explanation_pl}" if item.explanation_pl else ""))
            speak(V.reveal(item))
            _record(repo, pack, profile_id, session_id, sk, item, False, a, 4, now, agv)
            first[item.id] = False
            res_item = "wrong"
            break
        if item is None:                                   # pominięte: zostaje do zrobienia
            continue
        done.append(item.id)
        if res_item:
            results[item.id] = res_item
        plan = {**plan, "done": done, "ok": ok, "results": results}
        if agv:
            plan = {**plan, "agv": _agv_state(plan, agv, first, items, now)}
        if stage and all(i.id in done for i in items if stages.get(i.id) == stage):
            plan = _stage_done(repo, profile_id, session_id, plan, stage, items, now)
            if stage == "pre":
                say(pre_summary(plan, items))
        repo.set_session_plan(profile_id, session_id, plan)
    return Result(len(ok), len(done), skipped=skipped)


def _check_request(sk: C.Skill, items: list[C.Item], plan: dict):
    from tutor.pedagogy import evidence as EV
    cy = plan.get("cycle") or {}
    st = plan.get("stages") or {}
    ids = tuple(i.id for i in items if st.get(i.id) in ("pre", "post", "transfer", "check"))
    if not cy.get("category") or not ids:
        return None
    return EV.ConfirmRequest(sk.id, cy["category"], ids, bool(cy.get("unverified_items")), f"error:{cy['category']}")


def _record_check(repo, pack, pid, sid, req, stage, item, correct, a: Answer, hint_level, now) -> None:
    n_opt = len(item.options) if item.options else None
    if req is None:
        return
    ingest.apply_confirmation(repo, pack, pid, sid, req, item.id, correct, now=now, stage=stage,
                              dedupe_key=f"lesson:{sid}:{item.id}", response=a.text, hint_level=hint_level,
                              n_options=n_opt)


def _stage_done(repo, pid, sid, plan: dict, stage: str, items: list[C.Item], now: datetime) -> dict:
    """Etap zakończony: czas, wynik (dla `pre` także AGV przed wyjaśnieniem) i zdarzenie w dzienniku nauki."""
    from tutor.app import learnlog as LL
    from tutor.app import remediation as R
    st = plan.get("stages") or {}
    ids = [i.id for i in items if st.get(i.id) == stage]
    sc = R.score(plan.get("results") or {}, ids)
    cy = plan.get("cycle") or {}
    plan = {**plan, "stage_at": {**(plan.get("stage_at") or {}), stage: now.strftime("%Y-%m-%dT%H:%M:%SZ")}}
    if stage == "pre":
        res = plan.get("results") or {}
        plan["agv"] = {"category": cy.get("category"), "skill_id": cy.get("skill_id"),
                       "results": {i: res[i] == "independent" for i in ids if res.get(i) in ("independent", "wrong")},
                       "outcome": R.outcome(sc), "after_explanation": False, "stage": "pre",
                       "unverified_items": cy.get("unverified_items", False),
                       "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    LL.log(repo, pid, "log.remediation", sid, stage=stage, category=cy.get("category"),
           skill_id=cy.get("skill_id"), cycle=cy.get("kind"), items=ids, outcome=R.outcome(sc) if stage != "practice"
           else None, fresh=cy.get("fresh"), unverified_items=cy.get("unverified_items"),
           **{k: sc[k] for k in ("independent", "assisted", "wrong", "ambiguous", "n")})
    return plan


def pre_summary(plan: dict, items: list[C.Item]) -> str:
    """Po sprawdzeniu (dopiero teraz) pokazujemy odpowiedzi i uczciwy wniosek."""
    from tutor.app import remediation as R
    st, res = plan.get("stages") or {}, plan.get("results") or {}
    pre = [i for i in items if st.get(i.id) == "pre"]
    sc = R.score(res, [i.id for i in pre])
    lines = [f"\nSprawdzenie: {sc['independent']}/{sc['n']} poprawnie."]
    for i in pre:
        mark = {"independent": "✓", "wrong": "✗", "ambiguous": "?"}.get(res.get(i.id), "–")
        lines.append(f"  {mark} {i.prompt} → {i.answers[0]}")
    o = R.outcome(sc)
    lines.append({"confirmed": "Problem wystąpił w zadaniach — przejdźmy do wyjaśnienia.",
                  "not_confirmed": "W tych zadaniach problem nie wystąpił (to nie znaczy, że błędu w rozmowie nie "
                                   "było). Krótkie przypomnienie i ćwiczenia — możesz je pominąć („skip”).",
                  "inconclusive": "Wynik mieszany — przejdźmy do wyjaśnienia.",
                  "no_data": "Brak rozstrzygniętych odpowiedzi — sprawdzenie bez wyniku."}[o])
    return "\n".join(lines)


def _agv_request(pack: C.Pack, sk: C.Skill, items: list[C.Item], plan: dict):
    """ConfirmRequest dla lekcji wybranej z powtarzającego się błędu (`choice.source == "error"`), inaczej None."""
    from tutor.pedagogy import evidence as EV
    ch = plan.get("choice") or {}
    if ch.get("source") != "error" or not ch.get("category"):
        return None
    return EV.ConfirmRequest(sk.id, ch["category"], tuple(i.id for i in items),
                             any(i.review.status != "human_reviewed" for i in items), f"error:{ch['category']}")


def _agv_state(plan: dict, req, first: dict[str, bool], items: list[C.Item], now: datetime) -> dict:
    """Wynik potwierdzenia liczony z PIERWSZYCH prób (bez podpowiedzi). Ćwiczenie następuje po wyjaśnieniu, więc
    `not_confirmed` znaczy „umie w ćwiczeniu kontrolowanym”, a nie „błędu w rozmowie nie było”."""
    from tutor.pedagogy import evidence as EV
    prev = plan.get("agv") or {}
    res = {**prev.get("results", {}), **first}
    complete = all(i.id in res for i in items)
    return {"category": req.category, "skill_id": req.skill_id, "results": res,
            "outcome": EV.outcome(list(res.values())) if complete else "pending", "after_explanation": True,
            "unverified_items": req.unverified_items, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


def _record(repo, pack, pid, sid, sk, item, correct, a: Answer, hint_level, now, agv=None) -> None:
    n_opt = len(item.options) if item.options else None
    if agv is not None:                      # AGV: próba `remediation`, bez wpływu na status mastery
        ingest.apply_confirmation(repo, pack, pid, sid, agv, item.id, correct, now=now,
                                  dedupe_key=f"lesson:{sid}:{item.id}", response=a.text, hint_level=hint_level,
                                  n_options=n_opt)
        return
    ingest.apply_item_attempt(repo, pack, pid, sid, item.id, sk.id, correct, source="practice",
                              dedupe_key=f"lesson:{sid}:{item.id}", now=now, response=a.text,
                              hint_level=hint_level, n_options=n_opt, allow_mastery=False)


def _heard(a: Answer) -> str:
    low = f" (niepewne słowa: {', '.join(a.low_probs)})" if a.low_probs else \
        " (brak danych o pewności rozpoznania)" if a.low_probs is None else ""
    return f"  Usłyszałem: „{a.text}”{low}"


def judge(pack: C.Pack, skill_id: str, item: C.Item, a: Answer) -> str:
    """correct | finish | skip | help | unknown | unclear | wrong. `unclear` = niska pewność STT albo niejasna wypowiedź
    (nie jest błędem językowym i nie jest dopasowywana do oczekiwanej odpowiedzi); `unknown` = „nie wiem”."""
    if check(pack, item, a.text):
        return "correct"
    sig = intent.detect(a.text) if len(a.text.split()) <= MAX_INTENT_WORDS else None
    if sig:
        return sig
    if a.mode == "voice":
        heard = set(C.norm_answer(a.text).split())
        if a.low_probs is None or heard & set(a.low_probs) or not clear_attempt(pack, skill_id, item, a.text):
            return "unclear"
    return "wrong"


def stage_summary(plan: dict) -> str:
    """Wynik etapów z rzeczywistych prób (bez oceny modelu). Poprawny test ≠ trwałe opanowanie."""
    from tutor.app import remediation as R
    st, res = plan.get("stages") or {}, plan.get("results") or {}
    parts = []
    for k in ("pre", "practice", "post", "transfer", "check"):
        ids = [i for i in plan.get("items", []) if st.get(i) == k]
        if ids:
            parts.append(f"{R.STAGE_PL[k]}: {R._frac(R.score(res, ids))}")
    return ("\nWynik etapów — " + " · ".join(parts) + ". To wynik ćwiczeń, nie trwałe opanowanie; sprawdzimy go "
            "później na nowych zadaniach.") if parts else ""


def summary(res: Result) -> str:
    if res.moved_on:
        return ("\nĆwiczenia zakończone na Twoją prośbę. To nie oznacza opanowania umiejętności — "
                "opanowanie wymaga potwierdzenia w ćwiczeniach.")
    if res.skipped:
        return (f"\nPominięto {res.skipped} zadań z powodu niepewnego rozpoznania mowy — wrócą po wznowieniu lekcji "
                f"(to samo polecenie `--lesson`). Rozwiązane: {res.correct}/{res.total}.")
    return (f"\nWynik ćwiczeń: {res.correct}/{res.total} poprawnie. To wynik ćwiczeń, który nie oznacza opanowania "
            "umiejętności — opanowanie wymaga potwierdzenia w kolejnych dniach.")


def intro(pack: C.Pack, sk: C.Skill, choice: dict | None = None, plan: dict | None = None) -> str:
    why = f"Dlaczego ten cel: {choice['reason']}\n\n" if choice else ""
    if (plan or {}).get("stages"):                     # lekcja etapowa: wyjaśnienie dopiero po sprawdzeniu
        kinds = set(plan["stages"].values())
        flow = ("Plan: sprawdzenie → wyjaśnienie → ćwiczenia → samodzielny test." if "pre" in kinds else
                "Plan: wyjaśnienie → ćwiczenia → samodzielny test." if "practice" in kinds else
                "Plan: krótkie zadania kontrolne.")
        return f"Cel lekcji: {sk.id} ({sk.cefr}) — {sk.can_do_pl}\n{why}{flow} (q = przerwij, lekcję można wznowić)."
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
