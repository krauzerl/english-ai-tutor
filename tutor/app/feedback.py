"""Informacja zwrotna z rozmowy (F5.10) z istniejących obserwacji oceny; bez nowego klasyfikatora i bez wywołań LLM.

Zasady (04 §3): styl `summary` nigdy nie przerywa rozmowy (korekty w podsumowaniu na końcu); `periodic`/`intensive`
dają jeden niewymuszony recast w następnej odpowiedzi tutora wg `correction.select` (próg wagi, odstęp tur, cel lekcji).
Bierzemy tylko obserwacje `valid` z pewnością modelu `h`. `stt_suspect` to co najwyżej łagodne sprawdzenie
(„mogłem źle usłyszeć”), nigdy błąd ucznia.
"""
from __future__ import annotations

from tutor.pedagogy import correction as K
from tutor.pedagogy.content import Pack


def _candidates(repo, pack: Pack, pid: int, sid: int, goals: set[str], skip: set[int]) -> list[tuple[K.Candidate, str]]:
    out = []
    skip = set(skip) | repo.rejected_observation_ids(pid)          # F7: zakwestionowane przez ucznia
    for o in repo.list_observations(pid, sid, status="valid"):
        if o["kind"] not in ("error", "stt_suspect") or o["confidence"] != "h" or not o["fix"] or o["id"] in skip:
            continue
        out.append((K.Candidate(o["id"], o["turn_id"], o["category"] or "", o["skill_id"], o["severity"] or 1, 1,
                                o["skill_id"] in goals, o["span"], o["fix"]), o["kind"]))
    return out


def recast_directive(repo, pack: Pack, pid: int, sid: int, style: str, goals: set[str]) -> str | None:
    """Notatka dla tutora na JEDNĄ odpowiedź albo None. Zapisuje w planie sesji, co już było użyte."""
    if style == "summary":
        return None
    plan = repo.get_session_plan(pid, sid)
    st = plan.get("recast") or {"done": [], "last_turn": None, "cats": []}
    cands = _candidates(repo, pack, pid, sid, goals, set(st["done"]))
    if not cands:
        return None
    kinds = {c.obs_id: k for c, k in cands}
    turn_index = sum(1 for t in repo.list_turns(pid, sid) if t["role"] == "user")
    for d in K.select([c for c, _ in cands], style, turn_index=turn_index, last_correction_turn=st["last_turn"],
                      corrected_categories=set(st["cats"]), rubric=pack.rubric):
        if d.candidate is None:
            continue
        c = d.candidate
        repo.set_session_plan(pid, sid, {**plan, "recast": {"done": [*st["done"], c.obs_id], "last_turn": turn_index,
                                                            "cats": [*st["cats"], c.category]}})
        hedge = (" You may have misheard the student, so make it a friendly check, not a correction."
                 if kinds[c.obs_id] == "stt_suspect" else "")
        if len(st["done"]) % 2 == 1 and kinds[c.obs_id] == "error":   # zrównoważony: co druga korekta = samopoprawa
            return (f"Feedback note (never mention this note): earlier the student said “{c.span}”. In one short "
                    "friendly sentence, quote those words and invite the student to say them again in a better way "
                    "(for example: You said “...” — can you say that another way?). Do NOT give the correct form "
                    "yourself, do not explain grammar, and still react to what they just said.")
        return (f"Feedback note (never mention this note): earlier the student said “{c.span}”; the natural form is "
                f"“{c.fix}”. In your reply, use the natural form once, as part of a normal sentence (a gentle recast). "
                "Do not say they made a mistake, do not explain grammar, do not repeat it later, and still react to "
                f"what they just said.{hedge}")
    return None


def _explain(pack: Pack, category: str) -> str:
    cats = {c.id: c for c in pack.errors.categories}
    c = cats.get(category) or cats.get(category.split(".")[0])
    return c.explanation_pl if c else ""


_ART = {"a", "an", "the"}
_PREP = {"in", "on", "at", "to", "for", "of", "with", "by", "from", "about", "into", "onto", "during", "since"}


def explain_edit(pack: Pack, span: str, fix: str, category: str) -> str:
    """Wyjaśnienie dopasowane do RZECZYWISTEJ zmiany (wstawiony rodzajnik, końcówka -s, nieregularna forma…);
    ogólne wyjaśnienie kategorii tylko wtedy, gdy zmiana nie pasuje do żadnego wzorca."""
    from tutor.pedagogy import edits as E
    es = E.edits(span, (0, len(span)), fix)
    gen = _explain(pack, category)
    if len(es) == 1:
        old, new = [x.lower() for x in es[0].old], [x.lower() for x in es[0].new]
        if not old and len(new) == 1 and new[0] in _ART:
            return f"Przed tym rzeczownikiem potrzebny jest rodzajnik „{new[0]}”."
        if not new and len(old) == 1 and old[0] in _ART:
            return f"Tu rodzajnik „{old[0]}” jest zbędny."
        if not old and len(new) == 1 and new[0] in _PREP:
            return f"Brakuje przyimka „{new[0]}”."
        if len(old) == 1 and len(new) == 1:
            x, y = old[0], new[0]
            if x in _ART and y in _ART:
                return f"Tu pasuje „{y}”, nie „{x}”." + (f" {gen}" if gen else "")
            if x in _PREP and y in _PREP:
                return f"W tym wyrażeniu używamy przyimka „{y}”, nie „{x}”."
            if (x, y) in (("have", "has"), ("do", "does"), ("are", "is"), ("were", "was")):
                return f"Przy he/she/it (jedna osoba lub rzecz) mówimy „{y}”, nie „{x}”."
            if (y, x) in (("have", "has"), ("do", "does"), ("are", "is"), ("were", "was")):
                return f"Przy tym podmiocie (I/you/we/they lub liczba mnoga) mówimy „{y}”, nie „{x}”."
            if y in (x + "s", x + "es") or (x.endswith("y") and y == x[:-1] + "ies"):
                return f"Po he/she/it (jedna osoba lub rzecz) czasownik ma końcówkę -s: „{y}”, nie „{x}”."
            if x in (y + "s", y + "es"):
                return f"Przy tym podmiocie czasownik nie ma końcówki -s: „{y}”, nie „{x}”."
            if x.endswith("ed") and y in E._PAST_FORMS:
                return f"To czasownik nieregularny: forma przeszła to „{y}”, nie „{x}”."
            if y in ("was", "were") and x in ("was", "were"):
                return f"Z tym podmiotem mówimy „{y}”, nie „{x}”."
    return f"Naturalniej: „{fix}”." + (f" {gen}" if gen else "")


def summary_lines(repo, pack: Pack, pid: int, sid: int, pending: int = 0) -> list[str]:
    """3–5 najważniejszych problemów z przykładem, poprawką i wyjaśnieniem. `pending` > 0 = ocena niekompletna."""
    cands = _candidates(repo, pack, pid, sid, set(), set())
    if not cands:
        return [f"[Ocena niekompletna: {pending} wypowiedzi czeka na sprawdzenie — wynik pojawi się w historii "
                "rozmowy.]"] if pending else []
    kinds = {c.obs_id: k for c, k in cands}
    lines = ["Do poprawy w tej rozmowie (to sugestie modelu — mogę się mylić):"]
    for c in K.quiz([c for c, _ in cands], pack.rubric):
        why = explain_edit(pack, c.span, c.fix, c.category)
        line = f"• „{c.span}” → „{c.fix}”" + (f" — {why}" if why else "")
        if kinds[c.obs_id] == "stt_suspect":
            line += " (możliwe, że źle usłyszałem — sprawdź, czy tak powiedziałeś/aś)"
        lines.append(line)
    if pending:
        lines.append(f"[Ocena niekompletna: {pending} wypowiedzi czeka na sprawdzenie — pełne podsumowanie pojawi się "
                     "w historii rozmowy.]")
    return lines


# --- drabina pomocy L1–L4 w rozmowie (styl `intensive`) ---
_HINTS = {
    1: "Say only that something in that sentence could be said better and invite them to say it again "
       "(e.g. \u201cAlmost! Want to try that once more?\u201d). Do NOT give the correct form.",
    2: "Remind them in one short sentence which grammar point matters here: {topic} "
       "(e.g. \u201cThink about the {topic}.\u201d). Do NOT give the correct form; ask them to say it again.",
    3: "Your reply must contain this exact question: \u201cWhich is right: {a} or {b}?\u201d",
    4: "Your reply must contain the exact words \u201c{fix}\u201d, used naturally (for example by repeating their "
       "sentence correctly). Do not lecture.",
}


def _ladder_note(lad: dict, cat) -> str:
    topic = lad["category"].replace(".", " ").replace("_", " ")
    body = _HINTS[lad["level"]].format(topic=topic, a=lad["span"], b=lad["fix"], fix=lad["fix"])
    return (f"Feedback note (never mention this note): earlier the student said \u201c{lad['span']}\u201d "
            f"(natural form: \u201c{lad['fix']}\u201d). Correction step {lad['level']} of 4: {body} "
            "Keep it friendly and short, and still react to what they just said.")


def ladder_directive(repo, pack: Pack, pid: int, sid: int, goals: set[str], user_text: str) -> str | None:
    """Jedna notatka na odpowiedź. Maszyna stanów w `session.plan_json["ladder"]` (bez zapisu prób/mastery)."""
    plan = repo.get_session_plan(pid, sid)
    lad = plan.get("ladder")
    cats = {c.id: c for c in pack.errors.categories}
    if lad and not lad.get("done"):
        c = K.Ladder(lad["category"], lad.get("skill_id"), lad["span"], lad["fix"], lad["level"], False, None,
                     lad["tries"])
        res = K.check_attempt(user_text, c)
        if res == K.NEEDS_EVAL:
            lad["idle"] = lad.get("idle", 0) + 1
            if lad["idle"] >= 2:                          # rozmowa poszła dalej: nie męczymy ucznia
                lad["done"], lad["outcome"] = True, "dropped"
            repo.set_session_plan(pid, sid, {**plan, "ladder": lad})
            return None
        nxt, _ = K.advance(c, res)
        lad.update(level=nxt.level, tries=nxt.tries, done=nxt.done, outcome=nxt.outcome)
        repo.set_session_plan(pid, sid, {**plan, "ladder": lad})
        if nxt.done and nxt.outcome == "correct":
            return ("Feedback note (never mention this note): the student just corrected themselves. Acknowledge it in "
                    "two or three words at most and continue the conversation. Do not explain.")
        if nxt.done:
            return None
        return _ladder_note(lad, cats.get(lad["category"]) or cats.get(lad["category"].split(".")[0]))
    st = plan.get("recast") or {"done": [], "last_turn": None, "cats": []}
    cands = [(c, k) for c, k in _candidates(repo, pack, pid, sid, goals, set(st["done"])) if k == "error"]
    turn_index = sum(1 for t in repo.list_turns(pid, sid) if t["role"] == "user")
    for d in K.select([c for c, _ in cands], "intensive", turn_index=turn_index,
                      last_correction_turn=st["last_turn"], corrected_categories=set(st["cats"]), rubric=pack.rubric):
        if d.candidate is None:
            continue
        c = d.candidate
        lad = {"obs": c.obs_id, "category": c.category, "skill_id": c.skill_id, "span": c.span, "fix": c.fix,
               "level": 1, "tries": 0, "done": False, "outcome": None}
        repo.set_session_plan(pid, sid, {**plan, "ladder": lad, "recast": {
            "done": [*st["done"], c.obs_id], "last_turn": turn_index, "cats": [*st["cats"], c.category]}})
        return _ladder_note(lad, cats.get(c.category) or cats.get(c.category.split(".")[0]))
    return None


def directive(repo, pack: Pack, pid: int, sid: int, style: str, goals: set[str], user_text: str) -> str | None:
    """Wejście dla rozmowy: `intensive` = drabina L1–L4, `periodic` = pojedynczy recast, `summary` = nic w trakcie."""
    if style == "intensive":
        return ladder_directive(repo, pack, pid, sid, goals, user_text)
    return recast_directive(repo, pack, pid, sid, style, goals)
