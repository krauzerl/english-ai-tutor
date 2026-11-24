"""Idempotentne zapisy postępów (łączy `pedagogy/` ze `store/`). Nie jest integracją z rozmową (to F5).

Gwarancje (decyzja 3): ponowna analiza tej samej wypowiedzi albo tej samej próby NIE aktualizuje postępów dwa razy:
  * ledger tury (`turn_meta.applied_at`): ocena `evaluated` raz zastosowana ⇒ kolejne wywołania to no-op,
  * unikalne klucze wierszy (`observation_dedupe`, `attempt.dedupe_key`) + `INSERT OR IGNORE`,
  * stany pochodne (`skill_state`, `error_log`) liczone OD NOWA z prób/obserwacji, FSRS tylko przy NOWEJ próbie,
  * wszystko w jednej transakcji (awaria w środku = brak częściowych zapisów).
Rozróżnienie: `evaluated` z 0 obserwacji = wypowiedź POPRAWNA; `unrated`/`aborted`/`rejected` nie zmieniają postępów
(zapisują tylko status), a późniejsza ocena może je jeszcze zastosować.
"""
from __future__ import annotations

import dataclasses
import json
import re
from collections import Counter
from datetime import datetime

from tutor.pedagogy import errors as E
from tutor.pedagogy import evidence as EV
from tutor.pedagogy import mastery, srs
from tutor.pedagogy import retention as R
from tutor.pedagogy import vocab as V
from tutor.pedagogy.assessment import UttResult, content_words, prefilter
from tutor.pedagogy.cefr import level_index
from tutor.pedagogy.content import Pack, load_vocab, vocab_forms
from tutor.pedagogy.correction import NEEDS_EVAL  # noqa: F401  (obsługa niejednoznacznej próby: F5)
from tutor.pedagogy.mastery import SkillState
from tutor.store.repo import Repo

CONVERSATION = "conversation"


def quality_gate(pack: Pack) -> dict:
    return (pack.rubric.correction or {}).get("quality_gate", {})


def trusted(category: str | None, pack: Pack) -> bool:
    """Brama jakości (07 §5.5): tylko kategorie z `trusted_categories` (id albo rodzic) mogą zmieniać mastery.
    Domyślnie lista jest pusta: obserwacje z rozmowy są sugestiami, nie dowodem (ani przy braku błędu)."""
    tc = quality_gate(pack).get("trusted_categories", [])
    return bool(category) and any(category == t or category.startswith(t + ".") for t in tc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def skill_for_category(category: str, goals: set[str], pack: Pack) -> str | None:
    """Skill_id dla błędu: najpierw umiejętność-cel lekcji zawierająca kategorię (lub jej rodzica), potem żadna.
    Poza celem lekcji nie przypisujemy umiejętności (nie zgadujemy), więc błąd trafia tylko do `error_log`."""
    parent = E.core_of(category)
    for sid in sorted(goals):
        sk = pack.skills.get(sid)
        if sk and any(c == category or c == parent or (category == parent and c.startswith(parent + "."))
                      for c in sk.error_categories):
            return sid
    return None


def _recompute_skill(repo: Repo, pack: Pack, profile_id: int, skill_id: str, now: datetime,
                     theta: float | None = None) -> tuple[SkillState, SkillState]:
    """skill_state z historii prób (replay BKT) ⇒ idempotentne. Zwraca (poprzedni, nowy) do zdarzeń.

    Porażka testu trwałości zostawia w historii znacznik `relapse_reset`: BKT jest wtedy obcięty do `relapse_p_cap`,
    a „2 różne dni” liczą się od znacznika (nie można od razu odzyskać statusu starą historią)."""
    rb = pack.rubric
    row = repo.get_skill_state(profile_id, skill_id)
    prev = SkillState(skill_id) if row is None else SkillState(
        skill_id, row["p_mastery"], row["status"], row["attempts"], row["mastered_at"], row["verify_due_at"],
        row["verified_7d_at"], row["verified_30d_at"], row["relapses"])
    atts, last_reset = [], -1
    for i, a in enumerate(repo.attempt_history(profile_id, skill_id)):
        fb = json.loads(a["feedback_json"]) if a["feedback_json"] else {}
        if fb.get("relapse_reset"):
            last_reset = i
        atts.append({"correct": bool(a["correct"]), "bkt": fb.get("bkt") or mastery.bkt_source(
            a["source"], a["hint_level"], rb), "n_options": fb.get("n_options"), "day": a["day"],
            "hint_level": a["hint_level"], "reset": bool(fb.get("relapse_reset"))})
    sk = pack.skills.get(skill_id)
    p = rb.mastery["p_init_clamp"][0] if sk is None else mastery.p_init(theta, level_index(sk.cefr), rb)
    for a in atts:
        p = mastery.replay([a], rb, p) if not a["reset"] else min(p, rb.mastery["relapse_p_cap"])
    since = [a for a in atts[last_reset + 1:] if not a["reset"]]
    new = mastery.update_status(prev, p, since, sk.area if sk else "grammar", rb, now)
    new = dataclasses.replace(new, attempts=len([a for a in atts if not a["reset"]]))
    repo.upsert_skill_state(profile_id, skill_id, new.p, new.attempts, new.mastered_at, status=new.status,
                            verify_due_at=new.verify_due_at, verified_7d_at=new.verified_7d_at,
                            verified_30d_at=new.verified_30d_at, relapses=new.relapses, last_seen=_iso(now))
    return prev, new


def _recompute_errors(repo: Repo, pack: Pack, profile_id: int, now: datetime) -> list[dict]:
    """error_log z obserwacji (nadpisuje stan pochodny). Zwraca przejścia statusów."""
    obs = repo.list_observations(profile_id, status="valid")
    agg = E.aggregate(obs, now, pack.rubric)
    existing = {(r["category"], r["skill_id"]): r for r in repo.list_errors(profile_id)}
    events = []
    for (cat, sid), g in agg.items():
        prev_row = existing.get((cat, sid))
        prev = prev_row["status"] if prev_row else "active"
        reopened = prev_row["reopened"] if prev_row else 0
        resolved_at = prev_row["resolved_at"] if prev_row else None
        new_since = bool(resolved_at) and g["last_seen"] > resolved_at
        remediated = bool(sid) and any(a["source"] == "remediation" for a in repo.attempt_history(profile_id, sid))
        sessions = _opportunity_sessions(repo, profile_id, cat, sid, obs)
        status, reopened = E.next_status(
            prev, reopened, count_30d=g["count_30d"], utts_30d=g["utts_30d"], remediated=remediated,
            sessions=sessions, new_error_since_resolved=new_since, rubric=pack.rubric)
        repo.put_error_log(profile_id, cat, sid, count=g["count"], status=status, severity_max=g["severity_max"],
                           reopened=reopened, example=g["example"], correction=g["correction"],
                           example_observation_id=g["example_obs_id"], first_seen=g["first_seen"],
                           last_seen=g["last_seen"])
        if status != prev:
            events.append({"category": cat, "from": prev, "to": status})
    return events


def _opportunity_sessions(repo: Repo, profile_id: int, cat: str, sid: str | None, obs: list[dict]) -> list[dict]:
    """Sesje z okazją użycia: błąd tej kategorii lub poprawne użycie/zadanie umiejętności (jeden wiersz na sesję)."""
    by: dict[int, dict] = {}
    for o in obs:
        if o["category"] == cat and o["kind"] == "error" and o["confidence"] in ("h", "m"):
            by.setdefault(o["session_id"], {"errors": 0, "correct": 0})["errors"] += 1
    if sid:
        for a in repo.attempt_history(profile_id, sid):
            if a["session_id"] is not None and a["correct"]:
                by.setdefault(a["session_id"], {"errors": 0, "correct": 0})["correct"] += 1
    return [by[k] for k in sorted(by)]


def apply_turn_evaluation(repo: Repo, pack: Pack, profile_id: int, session_id: int, turn_id: int, result: UttResult,
                          *, input_mode: str, text: str, goals: set[str], now: datetime, model: str | None = None,
                          prompt_version: str | None = None, fluency: dict | None = None,
                          low_prob_words: list[str] | None = None, theta: dict[str, float] | None = None,
                          vocab_targets: list[str] | None = None, tutor_prev: str | None = None) -> dict:
    """Zapisuje wynik oceny jednej wypowiedzi. Zwraca {"applied": bool, "reason", "events": {...}}.

    `reason`: applied | already_applied | not_rated:<status> | stale. Ponowne wywołanie dla tej samej tury = no-op."""
    theta = theta or {}
    meta = repo.get_turn_meta(profile_id, turn_id)
    if meta and meta["applied_at"]:
        return {"applied": False, "reason": "already_applied", "events": {}}
    with repo.transaction():
        repo.put_turn_meta(profile_id, session_id, turn_id, input_mode, eval_status=result.eval_status,
                           comm=result.comm if result.rated else None,
                           comm_quote=result.comm_quote if result.rated else None, fluency=fluency,
                           low_prob_words=low_prob_words, model=model, prompt_version=prompt_version)
        if not result.rated:
            return {"applied": False, "reason": f"not_rated:{result.eval_status}", "events": {}}
        touched: set[str] = set()
        new_obs = gated = 0
        levels = Counter(lv for c in result.observations if (lv := EV.level(c, pack)))
        for c in result.observations:
            skill = skill_for_category(c.category, goals, pack) if (c.category and c.kind == "error") else None
            oid = repo.add_observation(profile_id, session_id, turn_id, c.kind or "error", c.span, category=c.category,
                                       skill_id=skill, fix=c.fix, severity=c.severity, confidence=c.confidence,
                                       status=c.status, drop_reason=c.drop_reason, model=c.source or model,
                                       prompt_version=prompt_version)
            if oid is None:
                continue
            new_obs += 1
            counted = c.kind == "error" and c.status == "valid" and c.confidence in E.counted_confidences(pack.rubric)
            if counted and skill and not trusted(c.category, pack):
                gated += 1          # sugestia: obserwacja i error_log zostają, BKT i statusy mastery bez zmian
            elif counted and skill:
                key = f"{CONVERSATION}:{turn_id}:{skill}:{E.core_of(c.category)}:{c.span.lower()}:0"
                aid = repo.add_attempt(profile_id, skill, False, session_id=session_id, response=c.span,
                                       source=CONVERSATION, hint_level=0, dedupe_key=key,
                                       feedback={"bkt": CONVERSATION, "category": c.category})
                if aid:
                    touched.add(skill)
            if c.self_repair and c.category:  # autonaprawa zła → dobra = dowód pozytywny (hint_level=0)
                sk2 = skill_for_category(c.category, goals, pack)
                if sk2 and trusted(c.category, pack):
                    aid = repo.add_attempt(profile_id, sk2, True, session_id=session_id, response=c.fix,
                                           source=CONVERSATION, hint_level=0, feedback={"bkt": CONVERSATION,
                                                                                         "self_repair": True},
                                           dedupe_key=f"{CONVERSATION}:{turn_id}:{sk2}:repair:{(c.fix or '').lower()}")
                    if aid:
                        touched.add(sk2)
        for pos, ok in [(p, True) for p in result.positives] + [(n, False) for n in result.negatives]:
            if not _confirmed_use(pack, pos, ok):
                gated += 1          # twierdzenie modelu bez potwierdzenia deterministycznego (target_patterns)
                continue
            aid = repo.add_attempt(profile_id, pos.skill_id, ok, session_id=session_id, response=pos.quote,
                                   source=CONVERSATION, hint_level=0, feedback={"bkt": CONVERSATION},
                                   dedupe_key=f"{CONVERSATION}:{turn_id}:{pos.skill_id}:{pos.quote.lower()}:{int(ok)}")
            if aid:
                touched.add(pos.skill_id)
                if ok:
                    _srs(repo, pack, profile_id, "construction", pos.skill_id, True, now)
        transitions = []
        for sid in sorted(touched):
            prev, new = _recompute_skill(repo, pack, profile_id, sid, now, theta.get(pack.skills[sid].area)
                                         if sid in pack.skills else None)
            if prev.status != new.status:
                transitions.append({"skill_id": sid, "from": prev.status, "to": new.status})
        err_events = _recompute_errors(repo, pack, profile_id, now)
        voc = _vocab_use(repo, pack, profile_id, session_id, text, vocab_targets or [], tutor_prev,
                         set(low_prob_words or []), [c.span for c in result.observations if c.kind == "error"], now)
        repo.mark_applied(profile_id, turn_id, _iso(now))
    return {"applied": True, "reason": "applied", "events": {"skills": transitions, "errors": err_events,
                                                              "new_observations": new_obs, "vocab": voc,
                                                              "gated": gated, "levels": dict(levels)}}


def _confirmed_use(pack: Pack, pos, ok: bool) -> bool:
    """Użycie konstrukcji celu zmienia mastery tylko po potwierdzeniu deterministycznym: `ok` — cytat pasuje do
    `target_patterns` umiejętności; `bad` (twierdzenie o błędzie) — tylko dla zaufanej kategorii umiejętności."""
    sk = pack.skills.get(pos.skill_id)
    if sk is None:
        return False
    if ok:
        return any(re.search(p, pos.quote, re.I) for p in sk.target_patterns)
    return any(trusted(c, pack) for c in sk.error_categories)


def _vocab_use(repo: Repo, pack: Pack, profile_id: int, session_id: int, text: str, targets: list[str],
               tutor_prev: str | None, low_prob: set[str], error_spans: list[str], now: datetime) -> list[dict]:
    """Poprawne użycie słowa-celu w rozmowie (07 §3.5). Samo wykrycie to NIE opanowanie: `active` dopiero po
    ≥ N użyciach w różnych sesjach. Użycie w spanie z błędem się nie liczy (idzie zwykłą ścieżką obserwacji)."""
    if not targets:
        return []
    ngsl, pre, out = load_vocab(pack.root.parent, pack.lang), prefilter(text, pack.disfluency), []
    low = " ".join(error_spans).lower()
    for lem in sorted(set(targets)):
        e = ngsl.get(lem)
        if e is None:
            continue
        forms = vocab_forms(e, pack.variants)
        if any(f in low.split() for f in forms) or not V.detect_use(text, pre, forms, pack.rubric,
                                                                    tutor_prev=tutor_prev, low_prob_words=low_prob):
            continue
        row = repo.get_vocab(profile_id, pack.lang, lem) or {}
        verified = bool(quality_gate(pack).get("bielik_benchmark_passed"))
        ch = V.apply_event(row, "used_ok", pack.rubric, session=session_id, verified=verified)
        repo.put_vocab(profile_id, pack.lang, lem, lemma=lem, last_used_at=_iso(now), **ch)
        card = repo.get_card(profile_id, "vocab", lem)
        if verified and card and card["due_at"] <= _iso(now):
            _srs(repo, pack, profile_id, "vocab", lem, True, now)
        out.append({"lemma": lem, "knowledge": ch.get("knowledge", row.get("knowledge", "unknown"))})
    return out


def record_vocab_recall(repo: Repo, pack: Pack, profile_id: int, lemma: str, correct: bool, *, now: datetime,
                        trigger: str | None = None) -> dict:
    """Wynik przywołania produkcyjnego słowa. Karta `vocab` powstaje TYLKO z wyzwalacza (07 §3.4) i w limitach;
    istniejąca karta dostaje ocenę FSRS."""
    day = _iso(now)[:10]
    with repo.transaction():
        row = repo.get_vocab(profile_id, pack.lang, lemma) or {}
        ch = V.apply_event(row, "recall_ok" if correct else "recall_fail", pack.rubric, day=day)
        repo.put_vocab(profile_id, pack.lang, lemma, lemma=lemma, **ch)
        made = False
        if repo.get_card(profile_id, "vocab", lemma):
            _srs(repo, pack, profile_id, "vocab", lemma, correct, now)
        elif trigger and V.card_allowed(trigger, pack.rubric, **dict(zip(
                ("active_cards", "new_today"), repo.vocab_card_stats(profile_id, day), strict=True))):
            _srs(repo, pack, profile_id, "vocab", lemma, correct, now)
            repo.put_vocab(profile_id, pack.lang, lemma, card_day=day)
            made = True
    return {"knowledge": ch.get("knowledge", row.get("knowledge", "unknown")), "card_created": made}


def _srs(repo: Repo, pack: Pack, profile_id: int, card_type: str, ref_id: str, correct: bool, now: datetime,
         hint_level: int = 0, partial: bool = False, elapsed_ms: int | None = None,
         item_type: str | None = None) -> None:
    row = repo.get_card(profile_id, card_type, ref_id)
    rating = srs.grade(pack.rubric, correct=correct, hint_level=hint_level, partial=partial,
                       elapsed_ms=elapsed_ms, item_type=item_type)
    j, due = srs.review(row["fsrs_json"] if row else None, rating, now, pack.rubric)
    repo.put_card(profile_id, card_type, ref_id, j, due)


def apply_item_attempt(repo: Repo, pack: Pack, profile_id: int, session_id: int | None, item_id: str,
                       skill_id: str, correct: bool, *, source: str, dedupe_key: str, now: datetime,
                       response: str | None = None, hint_level: int = 0, elapsed_ms: int | None = None,
                       n_options: int | None = None, bkt: str = "production", delay_days: int | None = None,
                       theta: float | None = None, agv: dict | None = None, allow_mastery: bool = True) -> dict:
    """Próba zadania z banku (diagnoza/ćwiczenie/naprawa/test trwałości). `dedupe_key` obowiązkowy:
    to ten sam klucz, który powtórzone wywołanie wyśle drugi raz ⇒ drugi raz nic nie zmienia."""
    with repo.transaction():
        fb = {"bkt": bkt, "n_options": n_options, "item_id": item_id, **({"agv": agv} if agv else {})}
        if delay_days is not None:
            fb["delay_days"] = delay_days
        aid = repo.add_attempt(profile_id, skill_id, correct, session_id=session_id, item_id=item_id,
                               response=response, feedback=fb, source=source, hint_level=hint_level,
                               dedupe_key=dedupe_key)
        if aid is None:
            return {"applied": False, "reason": "already_applied"}
        prev, new = _recompute_skill(repo, pack, profile_id, skill_id, now, theta)
        if not allow_mastery and new.status == "mastered" and prev.status not in mastery.MASTERED:
            # ćwiczenia nie nadają statusu opanowania (wymaga zrecenzowanego potwierdzenia): zostaje `learning`
            new = dataclasses.replace(new, status="learning", mastered_at=None, verify_due_at=None)
            repo.upsert_skill_state(profile_id, skill_id, new.p, new.attempts, None, status="learning",
                                    verify_due_at=None, verified_7d_at=new.verified_7d_at,
                                    verified_30d_at=new.verified_30d_at, relapses=new.relapses,
                                    last_seen=_iso(now))
        _srs(repo, pack, profile_id, "skill_check" if prev.status in mastery.MASTERED else "construction",
             skill_id, correct, now, hint_level=hint_level, elapsed_ms=elapsed_ms,
             item_type=pack.items[item_id].type if item_id in pack.items else None)
    return {"applied": True, "reason": "applied", "from": prev.status, "to": new.status}


def apply_confirmation(repo: Repo, pack: Pack, profile_id: int, session_id: int | None, req, item_id: str,
                       correct: bool, *, now: datetime, dedupe_key: str, response: str | None = None,
                       hint_level: int = 0) -> dict:
    """Kontrakt F5 (AGV): wynik niezależnego zadania potwierdzającego problem z rozmowy (`evidence.ConfirmRequest`).
    To zwykła próba zadania (źródło `remediation`, BKT `production`) — jedyna droga do oceny `confirmed`.
    Wynik całej prośby: `evidence.outcome([...])` po wszystkich zadaniach."""
    if item_id not in req.item_ids:
        raise ValueError(f"{item_id} nie należy do prośby o potwierdzenie")
    return apply_item_attempt(repo, pack, profile_id, session_id, item_id, req.skill_id, correct,
                              source="remediation", dedupe_key=dedupe_key, now=now, response=response,
                              hint_level=hint_level, agv={"category": req.category, "reason": req.reason})


def words_in(text: str, pack: Pack) -> int:
    return content_words(text, prefilter(text, pack.disfluency))


def apply_retention_result(repo: Repo, pack: Pack, profile_id: int, skill_id: str, session_id: int | None,
                           results: list[dict], *, run_key: str, now: datetime) -> dict:
    """Wynik testu trwałości (7/30 d). `results`: {item_id, correct, productive, bkt, n_options?, response?}.
    Idempotentne po `run_key`: ponowne wysłanie tego samego testu nic nie zmienia. Porażka ⇒ `learning`,
    p ≤ relapse_p_cap, relapses+1 oraz znacznik `relapse_reset` w historii prób."""
    rb = pack.rubric
    row = repo.get_skill_state(profile_id, skill_id)
    if row is None:
        raise ValueError("brak stanu umiejętności")
    st = SkillState(skill_id, row["p_mastery"], row["status"], row["attempts"], row["mastered_at"],
                    row["verify_due_at"], row["verified_7d_at"], row["verified_30d_at"], row["relapses"])
    stage = R.stage_of(st)
    if stage is None:
        return {"applied": False, "reason": f"not_awaiting:{st.status}"}
    delay = R.delay_days(st, now)
    with repo.transaction():
        fresh = 0
        for r in results:
            aid = repo.add_attempt(profile_id, skill_id, r["correct"], session_id=session_id, item_id=r["item_id"],
                                   response=r.get("response"), source="retention", hint_level=0,
                                   feedback={"bkt": r.get("bkt", "production"), "n_options": r.get("n_options"),
                                             "stage": stage, "delay_days": delay},
                                   dedupe_key=f"retention:{skill_id}:{run_key}:{r['item_id']}")
            fresh += aid is not None
        if fresh == 0:
            return {"applied": False, "reason": "already_applied"}
        ok = R.passed([(r["correct"], r["productive"]) for r in results], rb)
        new = R.apply_result(st, ok, now, rb)
        if not ok:
            repo.add_attempt(profile_id, skill_id, False, session_id=session_id, source="retention",
                             feedback={"bkt": "production", "relapse_reset": True, "stage": stage},
                             dedupe_key=f"retention:{skill_id}:{run_key}:reset")
        repo.upsert_skill_state(profile_id, skill_id, new.p, row["attempts"], new.mastered_at, status=new.status,
                                verify_due_at=new.verify_due_at, verified_7d_at=new.verified_7d_at,
                                verified_30d_at=new.verified_30d_at, relapses=new.relapses, last_seen=_iso(now))
        _srs(repo, pack, profile_id, "skill_check", skill_id, ok, now)
    return {"applied": True, "reason": "applied", "passed": ok, "from": st.status, "to": new.status,
            "delay_days": delay}
