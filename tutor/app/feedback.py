"""Informacja zwrotna z rozmowy (F5.10) z istniejących obserwacji oceny; bez nowego klasyfikatora i bez wywołań LLM.

Zasady (04 §3): styl `summary` nigdy nie przerywa rozmowy (korekty w podsumowaniu na końcu); `periodic`/`intensive`
dają jeden niewymuszony recast w następnej odpowiedzi tutora wg `correction.select` (próg wagi, odstęp tur, cel lekcji).
Bierzemy tylko obserwacje `valid` z pewnością modelu `h`. `stt_suspect` to co najwyżej łagodne sprawdzenie
(„mogłem źle usłyszeć”), nigdy błąd ucznia.
"""
from __future__ import annotations

from tutor.pedagogy import correction as K
from tutor.pedagogy.content import Pack
from tutor.voice.conversation import SAY


def _candidates(repo, pack: Pack, pid: int, sid: int, goals: set[str], skip: set[int]) -> list[tuple[K.Candidate, str]]:
    out = []
    skip = set(skip) | repo.rejected_observation_ids(pid)          # F7: zakwestionowane przez ucznia
    counts = {e["category"]: e.get("count") or 1 for e in repo.list_errors(pid)}   # było na stałe 1
    for o in repo.list_observations(pid, sid, status="valid"):
        if o["kind"] not in ("error", "stt_suspect") or o["confidence"] != "h" or not o["fix"] or o["id"] in skip:
            continue
        out.append((K.Candidate(o["id"], o["turn_id"], o["category"] or "", o["skill_id"], o["severity"] or 1,
                                counts.get(o["category"], 1), o["skill_id"] in goals, o["span"], o["fix"]), o["kind"]))
    return out


def _discussed(repo, pid: int) -> set[str]:
    """Kategorie, które były już korygowane w rozmowie (recast/drabina) w dowolnej sesji tego profilu."""
    out: set[str] = set()
    for s in repo.list_sessions(pid):
        if s["kind"] in ("chat", "lesson", "voice"):
            out |= set(((repo.get_session_plan(pid, s["id"]) or {}).get("recast") or {}).get("cats") or [])
    return out


def _log(repo, pid: int, sid: int, c: K.Candidate, kind: str, tier: str, why: str, decision: str) -> None:
    """Decyzja o korekcie w dzienniku nauki (`log.correction`; bez tekstu w JSONL). Nigdy nie rzuca."""
    from tutor.app import learnlog as LL
    LL.log(repo, pid, "log.correction", sid, observation_id=c.obs_id, turn_id=c.turn_id, category=c.category,
           severity=c.severity, tier=tier, reason=why, decision=decision, stt_suspect=kind == "stt_suspect",
           model_confidence="h", count_30d=c.count_30d, verified=False)


def _tiers(repo, pack: Pack, pid: int, sid: int, cands, plan: dict) -> dict[int, tuple[str, str]]:
    texts = {t["id"]: t["text"] for t in repo.list_turns(pid, sid)}
    disc = _discussed(repo, pid)
    return {c.obs_id: K.impact(texts.get(c.turn_id, ""), c.span, c.fix, c.category, count_30d=c.count_30d,
                               discussed=c.category in disc, rubric=pack.rubric) for c, _ in cands}


RECENT_TURNS = 2     # korekta „natychmiastowa” tylko dla wypowiedzi z ostatnich 2 tur ucznia; starsze → podsumowanie


def recast_directive(repo, pack: Pack, pid: int, sid: int, style: str, goals: set[str]) -> str | None:
    """Notatka dla tutora na JEDNĄ odpowiedź albo None. Zapisuje w planie sesji, co już było użyte.

    Polityka rozmowy (`periodic`): błąd poważny (`K.impact`: zmiana sensu, rozbita negacja, powtarzający się
    i omawiany) → krótka jawna korekta w najbliższej odpowiedzi; zwykły błąd gramatyczny → delikatny recast co
    kilka tur (jak dotąd); drobny (przyimek, rodzajnik, słownictwo, styl, warianty) → tylko podsumowanie.
    Podejrzenie STT → pytanie „Did you mean…?” wyłącznie, gdy dotyczy sensu; inaczej nic."""
    if style == "summary":
        return None
    plan = repo.get_session_plan(pid, sid)
    st = plan.get("recast") or {"done": [], "last_turn": None, "cats": []}
    cands = _candidates(repo, pack, pid, sid, goals, set(st["done"]))
    if not cands:
        return None
    kinds = {c.obs_id: k for c, k in cands}
    tiers = _tiers(repo, pack, pid, sid, cands, plan)
    users = [t["id"] for t in repo.list_turns(pid, sid) if t["role"] == "user"]
    turn_index = len(users)
    recent = set(users[-RECENT_TURNS:])
    logged = set(plan.get("corr_logged") or [])

    def use(c: K.Candidate, decision: str) -> None:
        keys = {"recast": {"done": [*st["done"], c.obs_id], "last_turn": turn_index, "cats": [*st["cats"], c.category]},
                "corr_logged": sorted(logged | {c.obs_id})}
        if kinds[c.obs_id] == "error":          # uptake: czy uczeń sam użyje poprawionej formy w oknie tur
            keys["reuse_targets"] = K.add_reuse_target(plan, skill_id=c.skill_id, category=c.category, fix=c.fix,
                                                       from_turn=turn_index, span=c.span,
                                                       obs_id=c.obs_id)["reuse_targets"]
        repo.set_session_plan_keys(pid, sid, **keys)       # tylko własne klucze: bez nadpisania `uptake` z oceny
        _log(repo, pid, sid, c, kinds[c.obs_id], *tiers[c.obs_id], decision)

    serious = sorted((c for c, k in cands if tiers[c.obs_id][0] == K.SERIOUS and c.turn_id in recent),
                     key=lambda c: -c.turn_id)
    for c in serious:
        if kinds[c.obs_id] == "stt_suspect":          # może to Whisper: pytamy o sens, nie poprawiamy
            use(c, "ask_stt")
            return (f"Feedback note (never mention this note): you are not sure you heard the student correctly: "
                    f"they may have said “{c.span}” or “{c.fix}”, which mean different things. Ask very briefly "
                    f"“Did you mean {c.fix}?” and then continue the conversation. Do not call it a mistake.")
        use(c, "immediate")
        why = K.pair_note(_text(repo, pid, sid, c.turn_id), c.span, c.fix)
        say = f"Quick note: we say “{c.fix}” here, not “{c.span}”." + (f" {why[0].upper()}{why[1:]}." if why else "")
        # zdanie korekty wypowiada kod (Qwen3 na żywo ignorował notatkę z prośbą o korektę); model tylko kontynuuje
        return (f"{SAY}{say}{SAY}Feedback note (never mention this note): you have just said this short correction "
                f"at the start of your reply: {say} Do not repeat or extend it and do not mention other mistakes; "
                "continue the conversation by reacting to what the student said.")
    new = [c for c, _ in cands if c.obs_id not in logged]
    for c in new:                                       # drobne i STT bez wpływu na sens: tylko do podsumowania
        if (tiers[c.obs_id][0] == K.MINOR and not c.is_goal) or kinds[c.obs_id] == "stt_suspect":
            _log(repo, pid, sid, c, kinds[c.obs_id], *tiers[c.obs_id],
                 "skipped_stt" if kinds[c.obs_id] == "stt_suspect" else "deferred_summary")
    gram = [c for c, k in cands if k == "error" and (tiers[c.obs_id][0] != K.MINOR or c.is_goal)]   # cel lekcji
    done_log = {c.obs_id for c in new if c not in gram}
    if done_log:
        logged |= done_log
        repo.set_session_plan_keys(pid, sid, corr_logged=sorted(logged))
    for d in K.select(gram, style, turn_index=turn_index, last_correction_turn=st["last_turn"],
                      corrected_categories=set(st["cats"]), rubric=pack.rubric):
        if d.candidate is None:
            continue
        c = d.candidate
        alt = len(st["done"]) % 2 == 1                  # zrównoważony: co druga korekta = samopoprawa
        use(c, "self_repair_prompt" if alt else "recast")
        if alt:
            return (f"Feedback note (never mention this note): earlier the student said “{c.span}”. In one short "
                    "friendly sentence, quote those words and invite the student to say them again in a better way "
                    "(for example: You said “...” — can you say that another way?). Do NOT give the correct form "
                    "yourself, do not explain grammar, and still react to what they just said.")
        return (f"Feedback note (never mention this note): earlier the student said “{c.span}”; the natural form is "
                f"“{c.fix}”. In your reply, use the natural form once, as part of a normal sentence (a gentle recast). "
                "Do not say they made a mistake, do not explain grammar, do not repeat it later, and still react to "
                "what they just said.")
    return None


def _text(repo, pid: int, sid: int, turn_id: int) -> str:
    return next((t["text"] for t in repo.list_turns(pid, sid) if t["id"] == turn_id), "")


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
            if K._ing_ed(x, y):
                return ("Końcówka „-ed” mówi, jak ktoś się czuje (bored = znudzony), a „-ing” — jaka jest rzecz lub "
                        f"osoba (boring = nudny). Tu: „{y}”.")
            if {x, y} <= {"borrow", "lend", "borrowed", "lent", "borrows", "lends"}:
                return "„borrow” = pożyczyć OD kogoś, „lend” = pożyczyć KOMUŚ. Tu: " + f"„{y}”."
            if x in _ART and y in _ART:
                return f"Tu pasuje „{y}”, nie „{x}”." + (f" {gen}" if gen else "")
            if x in _PREP and y in _PREP:
                return f"W tym wyrażeniu używamy przyimka „{y}”, nie „{x}”."
            if (x, y) in (("have", "has"), ("do", "does"), ("are", "is"), ("were", "was")):
                return f"Przy he/she/it (jedna osoba lub rzecz) mówimy „{y}”, nie „{x}”."
            if (y, x) in (("have", "has"), ("do", "does"), ("are", "is"), ("were", "was")):
                return f"Przy tym podmiocie (I/you/we/they lub liczba mnoga) mówimy „{y}”, nie „{x}”."
            plural = y in (x + "s", x + "es") or (x.endswith("y") and y == x[:-1] + "ies")
            singular = x in (y + "s", y + "es") or (y.endswith("y") and x == y[:-1] + "ies")
            if (plural or singular) and not category.startswith("agreement.subject_verb"):   # audyt F7: rzeczownik
                return (f"Tu pasuje liczba {'mnoga' if plural else 'pojedyncza'} rzeczownika: „{y}”, nie „{x}”."
                        if "number" in category or "plural" in category else gen)
            if plural:
                return f"Po he/she/it (jedna osoba lub rzecz) czasownik ma końcówkę -s: „{y}”, nie „{x}”."
            if singular:
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
        _log(repo, pid, sid, c, kinds[c.obs_id], *K.impact(_text(repo, pid, sid, c.turn_id), c.span, c.fix,
                                                          c.category, rubric=pack.rubric), "summary_shown")
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
        hist = plan.get("ladder_history", []) + ([nxt.outcome] if nxt.done else [])   # F7: osiągnięcia „samopoprawa”
        repo.set_session_plan(pid, sid, {**plan, "ladder": lad, "ladder_history": hist})
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
        _log(repo, pid, sid, c, "error", *K.impact(_text(repo, pid, sid, c.turn_id), c.span, c.fix, c.category,
                                                   rubric=pack.rubric), "ladder")
        repo.set_session_plan(pid, sid, {**plan, "ladder": lad, "recast": {
            "done": [*st["done"], c.obs_id], "last_turn": turn_index, "cats": [*st["cats"], c.category]}})
        return _ladder_note(lad, cats.get(c.category) or cats.get(c.category.split(".")[0]))
    return None


def directive(repo, pack: Pack, pid: int, sid: int, style: str, goals: set[str], user_text: str) -> str | None:
    """Wejście dla rozmowy: `intensive` = drabina L1–L4, `periodic` = pojedynczy recast, `summary` = nic w trakcie."""
    if style == "intensive":
        return ladder_directive(repo, pack, pid, sid, goals, user_text)
    return recast_directive(repo, pack, pid, sid, style, goals)
