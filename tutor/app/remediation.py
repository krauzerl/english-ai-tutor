"""Nauka na powtarzających się błędach: sprawdzenie → wyjaśnienie → ćwiczenia → test samodzielny → transfer.

Rozbudowa istniejących elementów (lekcja, AGV, planer `goal.choose`, retencja), nie osobny system. Stan żyje w planie
sesji (`session.plan_json`): `stages` {item_id: etap}, `results` {item_id: wynik}, `stage_at` {etap: czas},
`cycle` {category, skill_id, kind}. Próby zadań kontrolnych zapisuje `ingest.apply_confirmation` (źródło
`remediation`, `no_mastery`); ćwiczenia z podpowiedziami to zwykłe `practice` z `allow_mastery=False`.

Zasady dowodu:
* sprawdzenie wstępne (`pre`) jest PRZED wyjaśnieniem, bez podpowiedzi — tylko ono mówi, czy problem wystąpił
  w zadaniu; poprawny wynik nie dowodzi, że błędu w rozmowie nie było;
* test samodzielny (`post`) i transfer używają INNYCH zadań niż sprawdzenie i ćwiczenia;
* wyniki: `independent` (samodzielnie, za pierwszym razem), `assisted` (po podpowiedzi/przypomnieniu), `wrong`,
  `ambiguous` (niepewne rozpoznanie mowy — nie liczy się ani jako błąd, ani jako sukces);
* żaden wynik nie nadaje opanowania (mastery zostaje zamknięte); brak zadań = brak danych, nie ocena.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from tutor.pedagogy import content as C
from tutor.pedagogy import evidence as EV

CHECK_STAGES = ("pre", "post", "transfer", "check")   # bez podpowiedzi wpływających na wynik
STAGE_PL = {"pre": "Sprawdzenie wstępne", "practice": "Ćwiczenia", "post": "Test samodzielny",
            "transfer": "Transfer (nowe zadania po przerwie)", "check": "Sprawdzenie głosowe w Quick Chat"}
RESULTS = ("independent", "assisted", "wrong", "ambiguous")
N_CHECK = 2            # zadań w sprawdzeniu wstępnym / teście / transferze / sprawdzeniu w rozmowie
N_PRACTICE = 3
TRANSFER_DAYS = 3      # transfer najwcześniej po tylu dniach od testu samodzielnego (jak retencja w `growth`)
RETRY_DAYS = 1         # powtórna lekcja po nieudanym teście najwcześniej następnego dnia
MAX_LESSONS = 2        # tyle lekcji na kategorię w 14 dniach; potem nie proponujemy w kółko tej samej lekcji
CHAT_CHECK_DAYS = 2    # sprawdzenie głosowe na starcie Quick Chat najwyżej co tyle dni


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")[:25].rstrip("Z"))


def closed(item: C.Item) -> bool:
    return item.type not in C.OPEN_TYPES and bool(item.answers)


def seen_items(repo, pid: int, skill_id: str) -> set[str]:
    return {a["item_id"] for a in repo.attempt_history(pid, skill_id) if a["item_id"]}


def staged(pack: C.Pack, skill_id: str, seen: set[str], allow: bool) -> dict[str, list[C.Item]]:
    """Podział zadań ćwiczeniowych na etapy: najpierw NIEWIDZIANE do sprawdzenia i testu (pamięć zadania to nie
    umiejętność), znane do ćwiczeń. Za mało zadań ⇒ mniej zadań kontrolnych albo żadne (brak danych)."""
    cands = [i for i in C.select_items(pack, pool="practice", purpose="practice", skill_id=skill_id,
                                       allow_unreviewed_practice=allow) if closed(i)]
    cands.sort(key=lambda i: (i.id in seen, "diagnosis" in i.pools, i.difficulty, i.id))
    k = N_CHECK if len(cands) >= 2 * N_CHECK + 1 else 1 if len(cands) >= 3 else 0
    pre, post = cands[:k], cands[k:2 * k]
    practice = sorted(cands[2 * k:], key=lambda i: (i.difficulty, i.id))[:N_PRACTICE]   # rosnąca trudność
    return {"pre": pre, "practice": practice, "post": post}


def fresh_items(pack: C.Pack, skill_id: str, seen: set[str], allow: bool, avoid_domains: set[str] = frozenset(),
                n: int = N_CHECK) -> list[C.Item]:
    """Nowe zadania do transferu / sprawdzenia w rozmowie: pula `retention` (nigdy nie ćwiczona w lekcji), potem
    `practice`; najpierw inny kontekst (`domain`) niż w lekcji. Zadania niezrecenzowane mają etykietę w wyniku."""
    out: list[C.Item] = []
    for pool in ("retention", "practice"):
        out += [i for i in C.select_items(pack, pool=pool, purpose="practice", skill_id=skill_id,
                                          allow_unreviewed_practice=allow)
                if closed(i) and i.id not in seen and i not in out]
    out.sort(key=lambda i: (i.domain in avoid_domains, "retention" not in i.pools, i.id))
    return out[:n]


def score(results: dict, ids: list[str]) -> dict:
    r = [results.get(i) for i in ids]
    sc = {k: r.count(k) for k in RESULTS}
    return {**sc, "n": len(ids), "answered": sum(1 for x in r if x)}


def outcome(sc: dict) -> str:
    """Wynik zadań kontrolnych: `confirmed` (wszystkie rozstrzygnięte błędne), `not_confirmed` (wszystkie
    samodzielnie poprawne), `inconclusive` (mieszane / z pomocą), `no_data` (brak rozstrzygniętych odpowiedzi)."""
    decided = [True] * sc["independent"] + [False] * (sc["wrong"] + sc["assisted"])
    if not decided:
        return "no_data"
    if sc["assisted"] and not sc["wrong"] and not sc["independent"]:
        return "inconclusive"
    return EV.outcome(decided)


def plan_for(stages: dict[str, list[C.Item]], cycle: dict) -> dict:
    items = [i.id for st in ("pre", "practice", "post", "transfer", "check") for i in stages.get(st, [])]
    return {"items": items, "done": [], "ok": [], "results": {}, "stage_at": {},
            "stages": {i.id: st for st, its in stages.items() for i in its}, "cycle": cycle,
            "domains": sorted({i.domain for its in stages.values() for i in its})}


# --- historia cykli ---
def _record(s: dict, plan: dict) -> dict | None:
    cy = plan.get("cycle")
    agv = plan.get("agv") or {}
    if not isinstance(cy, dict) and agv.get("category") and agv.get("outcome"):
        # plan sprzed etapów (B-lite): AGV po wyjaśnieniu = odpowiednik testu po lekcji
        r = [bool(x) for x in (agv.get("results") or {}).values()] or \
            {"not_confirmed": [True], "confirmed": [False]}.get(agv.get("outcome"), [])
        sc = {"independent": sum(r), "assisted": 0, "wrong": len(r) - sum(r), "ambiguous": 0, "n": len(r),
              "answered": len(r)}
        return {"session_id": s["id"], "kind": "lesson", "category": agv["category"], "skill_id": agv.get("skill_id"),
                "started": s.get("started_at"), "at": agv.get("at") or s.get("started_at") or "",
                "stages": {"post": sc}, "stage_at": {"post": agv.get("at")} if agv.get("at") else {},
                "domains": [], "complete": agv.get("outcome") != "pending", "reason": None, "legacy": True,
                "unverified": agv.get("unverified_items", False), "fresh": None, "other_context": None}
    if not isinstance(cy, dict) or not plan.get("stages"):
        return None
    res, st = plan.get("results") or {}, plan["stages"]
    by = {k: [i for i in plan.get("items", []) if st.get(i) == k] for k in ("pre", "practice", "post", "transfer",
                                                                           "check")}
    stages = {k: score(res, v) for k, v in by.items() if v}
    at = max((plan.get("stage_at") or {}).values(), default=s.get("started_at") or "")
    return {"session_id": s["id"], "kind": cy.get("kind", "lesson"), "category": cy.get("category"),
            "skill_id": cy.get("skill_id"), "started": s.get("started_at"), "at": at, "stages": stages,
            "stage_at": plan.get("stage_at") or {}, "domains": plan.get("domains") or [],
            "complete": len(plan.get("done") or []) >= len(plan.get("items") or []),
            "reason": (plan.get("choice") or {}).get("reason"), "unverified": cy.get("unverified_items", False),
            "fresh": cy.get("fresh"), "other_context": cy.get("other_context")}


def history(repo, pid: int) -> dict[str, list[dict]]:
    """Cykle per kategoria błędu, od najstarszego: lekcje etapowe, transfery i sprawdzenia głosowe z Quick Chat."""
    out: dict[str, list[dict]] = {}
    for s in repo.list_sessions(pid):
        r = _record(s, repo.get_session_plan(pid, s["id"]) or {})
        if r and r["category"] and any(v["answered"] for v in r["stages"].values()):
            out.setdefault(r["category"], []).append(r)
    for v in out.values():
        v.sort(key=lambda r: (r["at"], r["session_id"]))
    return out


def recurrences(repo, pid: int, category: str, since: str) -> int:
    """Obserwacje tej kategorii po `since` (bez zakwestionowanych). To sugestie modelu, nie potwierdzenie."""
    rej = repo.rejected_observation_ids(pid)
    return sum(1 for o in repo.list_observations(pid, status="valid")
               if o["kind"] == "error" and o["category"] == category and o["id"] not in rej
               and o["created_at"] > since)


def _ok(sc: dict | None) -> bool:
    return bool(sc) and sc["independent"] > 0 and sc["independent"] == sc["n"] - sc["ambiguous"]


def decide(repo, pack: C.Pack, pid: int, err: dict, now: datetime, recs: list[dict], allow: bool,
           skill_id: str) -> tuple[str, str] | None:
    """Co planer robi z powtarzającym się błędem: ("lesson" | "transfer", uzasadnienie) albo None (nie wymuszamy).
    Kryteria: wynik sprawdzenia wstępnego, testu po lekcji, transferu, ponowne wystąpienie w rozmowie, liczba lekcji."""
    cat = err["category"]
    if not recs:
        return ("lesson", f"Powtarzający się błąd w rozmowach ({cat}). To sugestia modelu, niezweryfikowana — "
                "zaczniemy od krótkiego sprawdzenia bez podpowiedzi.")
    last = recs[-1]
    lessons_14d = [r for r in recs if r["kind"] == "lesson" and r["at"] >= _iso(now - timedelta(days=14))]
    capped = len(lessons_14d) >= MAX_LESSONS
    again = (err.get("last_seen") or "") > last["at"]
    day = _iso(now - timedelta(days=RETRY_DAYS))
    if again:
        if capped:
            return None          # 2 lekcje w 14 dniach: nie powtarzamy tej samej lekcji w kółko (raport to pokazuje)
        return ("lesson", f"Błąd ({cat}) pojawił się znowu w rozmowie po ostatnim sprawdzeniu "
                f"({last['at'][:10]}). To sugestia modelu — sprawdzimy go na nowych zadaniach.")
    st = last["stages"]
    if last["kind"] == "check":
        o = outcome(st["check"])
        if o in ("confirmed", "inconclusive") and not capped:
            return ("lesson", f"W sprawdzeniu głosowym ({last['at'][:10]}) problem z {cat} wystąpił: "
                    f"{st['check']['independent']}/{st['check']['n']} samodzielnie poprawnie. Krótka lekcja.")
        return None
    if last["kind"] == "transfer":
        if _ok(st.get("transfer")) or capped or last["at"] > day:
            return None
        t = st.get("transfer")
        return ("lesson", f"Po przerwie {t['independent']}/{t['n']} samodzielnie poprawnie ({cat}) — powtórzymy "
                "na innych zadaniach.") if t else None
    if not last["complete"]:
        return None if capped else ("lesson", f"Dokończmy lekcję o błędzie {cat} (przerwana {last['at'][:10]}).")
    post = st.get("post")
    if post and not _ok(post):
        if capped or last["at"] > day:
            return None
        return ("lesson", f"Test po lekcji: {post['independent']}/{post['n']} samodzielnie poprawnie ({cat}) — "
                "powtórzymy na innych zadaniach.")
    if _ok(post):
        done_transfer = any(r["kind"] == "transfer" and r["at"] >= last["at"] for r in recs)
        t_post = last["stage_at"].get("post") or last["at"]
        if not done_transfer and t_post <= _iso(now - timedelta(days=TRANSFER_DAYS)):
            if fresh_items(pack, skill_id, seen_items(repo, pid, skill_id), allow, set(last["domains"])):
                days = (now - _dt(t_post)).days
                return ("transfer", f"{days} dni temu test po lekcji ({cat}) poszedł samodzielnie. Teraz nowe "
                        "zadania w innym kontekście — sprawdzimy, czy umiejętność się utrzymała.")
    return None


def status_pl(recs: list[dict], err: dict | None = None) -> str:
    """Krótki, uczciwy status cyklu dla dziennika i raportu."""
    if not recs:
        return "bez sprawdzenia w zadaniach"
    last = recs[-1]
    again = err and (err.get("last_seen") or "") > last["at"]
    tail = " Po tym sprawdzeniu błąd znowu pojawił się w rozmowie (sugestia modelu)." if again else ""
    st = last["stages"]
    if last["kind"] == "check":
        return f"sprawdzenie głosowe: {_frac(st['check'])}.{tail}"
    if last["kind"] == "transfer":
        ok = _ok(st.get("transfer"))
        return ("po przerwie poprawnie na nowych zadaniach — poprawa w ćwiczeniach, nie trwałe opanowanie."
                if ok else f"po przerwie: {_frac(st['transfer'])} — do powtórki.") + tail
    if not last["complete"]:
        return "lekcja przerwana — do dokończenia." + tail
    if _ok(st.get("post")):
        return "test po lekcji samodzielnie poprawny; transfer jeszcze niesprawdzony (jednorazowy wynik)." + tail
    if st.get("post"):
        return f"test po lekcji: {_frac(st['post'])} — do powtórki." + tail
    return "lekcja bez testu samodzielnego (za mało zadań) — brak danych o efekcie." + tail


def _frac(sc: dict | None) -> str:
    if not sc:
        return "brak danych"
    extra = [f"{sc['assisted']} z pomocą" if sc["assisted"] else "",
             f"{sc['ambiguous']} niejednoznaczne" if sc["ambiguous"] else ""]
    extra = ", ".join(x for x in extra if x)
    weak = " — 1 zadanie, słaby dowód" if sc["n"] == 1 else ""
    return f"{sc['independent']}/{sc['n']} samodzielnie" + (f" ({extra})" if extra else "") + weak


def lines(recs: list[dict], repo=None, pid: int | None = None) -> list[str]:
    """Porównanie przed/po dla jednej kategorii (z rzeczywistych prób). Etapy, których nie było, są nazwane."""
    out = []
    lessons = [r for r in recs if r["kind"] == "lesson"]
    checks = [r for r in recs if r["kind"] == "check"]
    transfers = [r for r in recs if r["kind"] == "transfer"]
    for r in checks:
        out.append(f"{STAGE_PL['check']} {r['at'][:10]}: {_frac(r['stages'].get('check'))}")
    for r in lessons:
        st = r["stages"]
        parts = [f"{STAGE_PL[k]}: {_frac(st.get(k)) if st.get(k) else 'brak zadań'}" for k in ("pre", "practice",
                                                                                              "post")]
        if not r["complete"]:
            parts.append("lekcja przerwana")
        out.append(f"Lekcja {r['at'][:10]} (sesja {r['session_id']}): " + " · ".join(parts))
    if lessons:
        if transfers:
            for t in transfers:
                out.append(f"{STAGE_PL['transfer']} {t['at'][:10]}: {_frac(t['stages'].get('transfer'))}"
                           + (" — inny kontekst" if t.get("other_context") else ""))
        else:
            out.append(f"{STAGE_PL['transfer']}: jeszcze niesprawdzony")
    if repo is not None and recs:
        n = recurrences(repo, pid, recs[0]["category"], recs[-1]["at"])
        out.append(f"Ponowne wystąpienie w rozmowie po ostatnim sprawdzeniu: {n}× (sugestie modelu)")
    return out


# --- sprawdzenie głosowe na starcie Quick Chat ---
def chat_check(repo, pack: C.Pack, pid: int, now: datetime, allow: bool) -> dict | None:
    """Krótkie, porównywalne zadania kontrolne dla ucznia, który korzysta tylko z Quick Chat: najczęstszy
    powtarzający się błąd, 2 NOWE zadania zamknięte, najwyżej co `CHAT_CHECK_DAYS` dni. None = nie teraz."""
    hist = history(repo, pid)
    since = _iso(now - timedelta(days=CHAT_CHECK_DAYS))
    if any(r["at"] >= since for rs in hist.values() for r in rs):
        return None
    for e in sorted(repo.list_errors(pid), key=lambda e: (-e.get("count", 0), e["category"])):
        if not (e.get("status") == "recurring" or (e.get("count", 0) >= 3 and e.get("status") not in
                                                     ("resolved", "improving"))):
            continue
        cat, parent = e["category"], e["category"].split(".")[0]
        for sid in sorted(s for s in pack.skills if cat in pack.skills[s].error_categories) + \
                sorted(s for s in pack.skills if parent in pack.skills[s].error_categories
                       and cat not in pack.skills[s].error_categories):
            items = fresh_items(pack, sid, seen_items(repo, pid, sid), allow)
            if items:
                return {"category": cat, "skill_id": sid, "items": items}
    return None
