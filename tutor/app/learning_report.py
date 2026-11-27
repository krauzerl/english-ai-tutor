"""Raport z nauki (Markdown) i eksport do analizy (pilot). Tylko odczyt z SQLite; pliki 0600 w katalogu 0700.

Raport rozróżnia źródła wiedzy: sugestia modelu ≠ potwierdzony błąd; zakwestionowane przez ucznia i oznaczone jako
błąd rozpoznania mowy NIE są liczone jako błędy; pominięć modelu nie wykazujemy (brak niezależnej informacji), poza
zgłoszeniami ucznia, które pozostają niezweryfikowane. Liczba ćwiczeń nie jest miarą poprawy kompetencji.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from tutor.app import learnlog as LL

CASES_VERSION = 1
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d -]{7,}\d)(?!\w)")
_LONGNUM = re.compile(r"\b\d{5,}\b")


def _q(repo, sql: str, args: tuple) -> list[dict]:
    return [dict(r) for r in repo.conn.execute(sql, args)]


def _in(ts: str | None, since: str | None, until: str | None) -> bool:
    return bool(ts) and (since is None or ts >= since) and (until is None or ts < until)


def _turn_ctx(repo, pid: int, sid: int, tid: int | None, cache: dict) -> dict:
    """Poprzednia kwestia tutora, wypowiedź ucznia i następna odpowiedź tutora — kontekst do oceny korekty."""
    turns = cache.setdefault(sid, _q(repo, "SELECT id, role, text, input_mode, created_at FROM turn WHERE "
                                           "profile_id=? AND session_id=? ORDER BY id", (pid, sid)))
    idx = next((k for k, t in enumerate(turns) if t["id"] == tid), None)
    if idx is None:
        return {"session_id": sid, "turn_id": tid}
    prev = next((t["text"] for t in reversed(turns[:idx]) if t["role"] == "assistant"), None)
    nxt = next((t["text"] for t in turns[idx + 1:] if t["role"] == "assistant"), None)
    u = turns[idx]
    return {"session_id": sid, "turn_id": tid, "turn_index": idx, "tutor_before": prev, "utterance": u["text"],
            "input_mode": u["input_mode"], "tutor_after": nxt, "at": u["created_at"]}


def build(repo, pack, pid: int, *, since: str | None = None, until: str | None = None,
          session_id: int | None = None) -> dict:
    """Dane raportu dla okresu [since, until) albo jednej sesji (wtedy okres pomijamy)."""
    from tutor.app import goal as G
    from tutor.app import growth as GR
    from tutor.app import history as H
    from tutor.app import weakspots as WS
    sess = [s for s in repo.list_sessions(pid)
            if (s["id"] == session_id if session_id is not None else _in(s["started_at"], since, until))]
    sids = {s["id"] for s in sess}
    plans = {s["id"]: repo.get_session_plan(pid, s["id"]) or {} for s in sess}
    secs = {s["id"]: H.session_seconds(repo, pid, s["id"]) for s in sess}
    reviews = repo.observation_reviews(pid)
    obs = [o for o in repo.list_observations(pid) if o["session_id"] in sids]
    atts = [a for a in _q(repo, "SELECT * FROM attempt WHERE profile_id=? ORDER BY created_at, id", (pid,))
            if a["session_id"] in sids]
    metas = [m for s in sess for m in repo.list_turn_meta(pid, s["id"])]
    evs = [e for e in LL.events(repo, pid) if e["session_id"] in sids]
    pending = {k: v for k, v in repo.pending_by_session(pid).items() if k in sids}

    # A. przebieg
    kinds = Counter(s["kind"] for s in sess)
    topics = sorted({(plans[s["id"]].get("topic") or {}).get("pl", "") for s in sess if s["kind"] == "chat"} - {""})
    lessons = sorted({plans[s["id"]]["lesson"] for s in sess if plans[s["id"]].get("lesson")})
    status = Counter(s["status"] for s in sess)

    # B. błędy (tylko obserwacje ważne; przegląd ucznia wyłącza z liczenia)
    def verdict(o):
        r = reviews.get(o["id"])
        return r["verdict"] if r else None
    err = [o for o in obs if o["kind"] == "error" and o["status"] == "valid"]
    counted = [o for o in err if verdict(o) not in ("disputed", "stt_error")]
    by_cat: dict[str, dict] = {}
    cache: dict = {}
    for o in counted:
        c = by_cat.setdefault(o["category"] or "?", {"n": 0, "high": 0, "other": 0, "examples": []})
        c["n"] += 1
        c["high" if o["confidence"] == "h" else "other"] += 1
        if len(c["examples"]) < 3:
            ctx = _turn_ctx(repo, pid, o["session_id"], o["turn_id"], cache)
            c["examples"].append({"span": o["span"], "fix": o["fix"], "utterance": ctx.get("utterance"),
                                  "confidence": o["confidence"], "observation_id": o["id"]})
    ambiguous = [o for o in obs if o["status"] == "valid" and (o["kind"] == "variant" or
                                                             (o["kind"] == "error" and o["confidence"] != "h"))]
    recurring = [e for e in repo.list_errors(pid) if e["status"] == "recurring"]
    checks = G.agv_checks(repo, pid)

    # C. postępy (pierwsze samodzielne próby; liczba ćwiczeń nie jest miarą poprawy)
    skills: dict[str, dict] = defaultdict(lambda: {"first_ok": 0, "first_n": 0, "retries": 0, "hints": 0,
                                                    "sources": Counter()})
    seen_items: set[tuple] = set()
    for a in atts:
        k = skills[a["skill_id"]]
        k["sources"][a["source"]] += 1
        key = (a["session_id"], a["item_id"])
        if a["item_id"] and key in seen_items:
            k["retries"] += 1
            continue
        seen_items.add(key)
        k["first_n"] += 1
        k["first_ok"] += int(bool(a["correct"]) and a["hint_level"] == 0)
        k["hints"] += int(a["hint_level"] > 0)
    agv = [{"session_id": s["id"], **plans[s["id"]]["agv"]} for s in sess if (plans[s["id"]].get("agv") or {})
           .get("outcome")]
    uptake = [{"session_id": s["id"], **u} for s in sess for u in plans[s["id"]].get("uptake") or []]
    choices = [{"session_id": s["id"], "skill_id": plans[s["id"]].get("lesson"), **plans[s["id"]]["choice"]}
               for s in sess if isinstance(plans[s["id"]].get("choice"), dict)]
    now = datetime.now(UTC)
    growth = GR.build(repo, pack, pid, now)
    states = {r["skill_id"]: r for r in repo.list_skill_states(pid)}

    # D. problemy techniczne i jakościowe
    stt = Counter(e["data"].get("status") for e in evs if e["kind"] == "log.stt")
    errors = [e for e in evs if e["kind"] == "log.error"]
    rep = [e for e in evs if e["kind"].startswith("report.")]
    disputed = [o for o in obs if verdict(o) == "disputed"]
    stt_marked = [o for o in obs if verdict(o) == "stt_error"]
    eval_status = Counter(m["eval_status"] for m in metas)
    dropped = sum(1 for m in metas if m["dropped_at"])
    dropped_obs = [o for o in obs if o["status"] == "dropped"]
    cases = build_cases(repo, pack, pid, sess=sess, obs=obs, metas=metas, evs=evs, reviews=reviews, cache=cache)
    return {"profile_id": pid, "since": since, "until": until, "session_id": session_id,
            "generated_at": now.isoformat(timespec="seconds"), "app": LL.app_version(),
            "sessions": {"n": len(sess), "seconds": sum(secs.values()), "kinds": dict(kinds), "status": dict(status),
                         "topics": topics, "lessons": lessons, "user_turns": repo.conn.execute(
                             f"SELECT COUNT(*) FROM turn WHERE profile_id=? AND role='user' AND session_id IN "
                             f"({','.join('?' * len(sids)) or 'NULL'})", (pid, *sids)).fetchone()[0]},
            "errors": {"by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1]["n"])),
                       "ambiguous": len(ambiguous), "recurring": [
                           {"category": e["category"], "count": e["count"], "agv": (checks.get(e["category"]) or {})
                            .get("outcome")} for e in recurring]},
            "progress": {"skills": {k: {**v, "sources": dict(v["sources"]),
                                        "p": round(states[k]["p_mastery"], 2) if k in states else None,
                                        "status": states[k]["status"] if k in states else None}
                                    for k, v in sorted(skills.items())},
                         "agv": agv, "uptake": uptake, "choices": choices, "retention": growth.get("retention"),
                         "weak": [e["category"] for e in WS.build(repo, pack, pid, now)["errors"][:5]]},
            "technical": {"stt": dict(stt), "stt_marked": len(stt_marked), "disputed": len(disputed),
                          "reports": Counter(e["kind"].removeprefix("report.") for e in rep),
                          "errors": [{"where": e["data"].get("where"), "error": e["data"].get("error"),
                                      "session_id": e["session_id"], "at": e["created_at"]} for e in errors],
                          "eval_status": dict(eval_status), "pending_evals": sum(pending.values()),
                          "dropped_evals": dropped, "dropped_observations": Counter(
                              o["drop_reason"] or "?" for o in dropped_obs)},
            "cases": cases}


def build_cases(repo, pack, pid: int, *, sess, obs, metas, evs, reviews, cache) -> list[dict]:
    """Przypadki do przeglądu (E). Każdy ma kontekst do odtworzenia; `label` zawsze `unverified` — nie są to etykiety
    do testów, dopóki człowiek ich nie sprawdzi."""
    out: list[dict] = []
    obs_by_id = {o["id"]: o for o in obs}

    def add(kind: str, why: str, **kw):
        out.append({"case": len(out) + 1, "type": kind, "why": why, "label": "unverified", **kw})

    def o_info(o):
        return {"observation_id": o["id"], "kind": o["kind"], "category": o["category"], "span": o["span"],
                "fix": o["fix"], "confidence": o["confidence"], "status": o["status"], "drop_reason": o["drop_reason"],
                "model": o["model"], "prompt_version": o["prompt_version"]}
    for o in obs:
        r = reviews.get(o["id"])
        ctx = lambda o=o: _turn_ctx(repo, pid, o["session_id"], o["turn_id"], cache)  # noqa: E731
        if r and r["verdict"] in ("disputed", "stt_error"):
            add("disputed_correction" if r["verdict"] == "disputed" else "stt_flagged_correction",
                "uczeń zakwestionował korektę" if r["verdict"] == "disputed" else "uczeń: błąd rozpoznania mowy",
                context=ctx(), observation=o_info(o), review={"verdict": r["verdict"], "note": r["note"],
                                                             "at": r["created_at"]})
        elif o["status"] == "valid" and o["kind"] == "error" and o["confidence"] != "h":
            add("ambiguous_correction", "sugestia modelu o niskiej pewności (nie pokazana jako recast)",
                context=ctx(), observation=o_info(o))
        elif o["kind"] == "stt_suspect" and o["status"] == "valid":
            add("stt_suspect", "walidator: możliwy błąd rozpoznania mowy", context=ctx(), observation=o_info(o))
        elif o["status"] == "dropped":                 # walidator odrzucił: materiał do strojenia walidatorów
            add("dropped_suggestion", f"walidator odrzucił sugestię modelu ({o['drop_reason']})", context=ctx(),
                observation=o_info(o))
    for m in metas:
        if m["eval_status"] in ("rejected", "aborted") or m["dropped_at"]:
            add("evaluation_incomplete", f"ocena: {m['eval_status']}" + (" (porzucona)" if m["dropped_at"] else ""),
                context=_turn_ctx(repo, pid, m["session_id"], m["turn_id"], cache),
                eval={"status": m["eval_status"], "model": m["model"], "prompt_version": m["prompt_version"]})
    for e in evs:
        d = e["data"]
        if e["kind"] == "log.stt" and d.get("status") in ("corrected", "rerecord"):
            add("stt_transcript", "uczeń poprawił transkrypcję" if d["status"] == "corrected" else "ponowne nagranie",
                session_id=e["session_id"], at=e["created_at"], stt={k: d.get(k) for k in (
                    "status", "original", "corrected", "low_probs", "stt_s", "audio_s")})
        elif e["kind"].startswith("report."):
            o = obs_by_id.get(d.get("observation_id"))
            item = pack.items.get(d.get("item_id")) if d.get("item_id") else None
            add(e["kind"], LL.REPORT_KINDS.get(e["kind"].removeprefix("report."), e["kind"]),
                context=_turn_ctx(repo, pid, e["session_id"], d.get("turn_id"), cache) if e["session_id"] else {},
                observation=o_info(o) if o else None, quote=d.get("quote"), note=d.get("note"), at=e["created_at"],
                item={"item_id": item.id, "answers": list(item.answers or []), "skill_ids": list(item.skill_ids)}
                if item else ({"item_id": d.get("item_id")} if d.get("item_id") else None),
                attempt_id=d.get("attempt_id"))
        elif e["kind"] == "log.error":
            add("runtime_error", f"błąd wykonania ({d.get('where')})", session_id=e["session_id"],
                at=e["created_at"], error=d.get("error"), app=d.get("app"))
    return out


# --- Markdown ---
def _pct(a: int, n: int) -> str:
    return f"{a}/{n}" if n else "—"


def render(d: dict, pack=None) -> str:
    def cat(c: str) -> str:
        return f"`{c}`"
    s, e, p, t = d["sessions"], d["errors"], d["progress"], d["technical"]
    scope = f"sesja #{d['session_id']}" if d["session_id"] is not None else \
        f"{(d['since'] or 'początek')[:10]} – {(d['until'] or 'teraz')[:10]}"
    L = [f"# Raport z nauki — {scope}", "",
         f"Profil #{d['profile_id']} · wygenerowano {d['generated_at']} · aplikacja {d['app']}", "",
         "> Korekty pochodzą z modelu językowego (Qwen3) i są **sugestiami**, nie potwierdzonymi błędami. "
         "Wpisy zakwestionowane przez Ciebie lub oznaczone jako błąd rozpoznania mowy nie są liczone. "
         "Pominięte błędy nie są tu wykazywane (model ich nie zgłosił, a nie mamy niezależnej oceny).", "",
         "## A. Przebieg nauki", "",
         f"- Sesje: **{s['n']}** ({', '.join(f'{k}: {v}' for k, v in sorted(s['kinds'].items())) or '—'})",
         f"- Czas nauki (aktywny, przerwy > 5 min przycięte): **{round(s['seconds'] / 60)} min**",
         f"- Wypowiedzi ucznia w rozmowach: {s['user_turns']}",
         f"- Stan sesji: {', '.join(f'{k}: {v}' for k, v in sorted(s['status'].items())) or '—'}",
         f"- Tematy rozmów: {', '.join(s['topics']) or '—'}",
         f"- Lekcje (cele): {', '.join(f'`{x}`' for x in s['lessons']) or '—'}", "",
         "## B. Błędy i słabości", ""]
    if e["by_category"]:
        L += ["| kategoria | sugestie | wysoka pewność | inne |", "|---|---|---|---|"]
        L += [f"| {cat(c)} | {v['n']} | {v['high']} | {v['other']} |" for c, v in e["by_category"].items()]
        L += ["", "Przykłady (wypowiedź → sugerowana forma):", ""]
        for c, v in e["by_category"].items():
            for x in v["examples"]:
                L.append(f"- {cat(c)}: „{x['span']}” → „{x['fix']}” — w: _{x['utterance'] or '?'}_ "
                         f"(pewność {x['confidence']}, obs #{x['observation_id']})")
    else:
        L.append("Brak sugestii błędów w ocenionych wypowiedziach tego okresu.")
    L += ["", f"- Przypadki niejednoznaczne (niska pewność / wariant): {e['ambiguous']}"]
    for r in e["recurring"]:
        L.append(f"- Powtarzający się problem: {cat(r['category'])} ×{r['count']}"
                 + (f" — ćwiczenie kontrolne: {r['agv']}" if r["agv"] else " — bez ćwiczenia kontrolnego"))
    L += ["", "## C. Postępy", "",
          "Pierwsza samodzielna próba = pierwsza odpowiedź na dane zadanie w sesji, bez podpowiedzi. "
          "`p` to szacunek BKT, nie potwierdzone opanowanie (mastery zablokowane polityką).", ""]
    if p["skills"]:
        L += ["| umiejętność | 1. próby poprawnie | ponowne próby | z podpowiedzią | źródła | p (BKT) |",
              "|---|---|---|---|---|---|"]
        L += [f"| `{k}` | {_pct(v['first_ok'], v['first_n'])} | {v['retries']} | {v['hints']} | "
              f"{', '.join(f'{a}:{b}' for a, b in v['sources'].items())} | {v['p'] if v['p'] is not None else '—'} |"
              for k, v in p["skills"].items()]
    else:
        L.append("Brak ćwiczeń w tym okresie.")
    for a in p["agv"]:
        L.append(f"- Ćwiczenie kontrolne (sesja #{a['session_id']}): `{a.get('category')}` → **{a['outcome']}**")
    for u in p["uptake"]:
        L.append(f"- Ponowne użycie po korekcie (sesja #{u['session_id']}): `{u.get('category')}` → {u.get('result')} "
                 "(obserwacja, nie dowód opanowania)")
    for c in p["choices"]:
        L.append(f"- Dlaczego ta lekcja (sesja #{c['session_id']}, `{c.get('skill_id')}`): {c.get('reason')}")
    r = p.get("retention") or {}
    if r:
        L.append("- Retencja (nowe zadania po przerwie): "
                 + ", ".join(f"{k.replace('after_', '≥').replace('_days', ' dni')}: "
                             f"{_pct(v['correct'], v['n'])}" for k, v in r.items() if isinstance(v, dict)
                             and k.startswith("after_"))
                 + ("" if r.get("enough") else " — za mało danych na wniosek"))
    L.append(f"- Do dalszej pracy (dziennik słabych stron): {', '.join(map(cat, p['weak'])) or '—'}")
    L += ["", "## D. Problemy techniczne i jakościowe", "",
          f"- Korekty zakwestionowane przez Ciebie: {t['disputed']}; oznaczone jako błąd rozpoznania mowy: "
          f"{t['stt_marked']}",
          f"- Zgłoszenia: {', '.join(f'{k}: {v}' for k, v in t['reports'].items()) or '—'}",
          f"- STT (rozpoznanie mowy): {', '.join(f'{k}: {v}' for k, v in sorted(t['stt'].items(), key=str)) or '—'}",
          f"- Oceny wypowiedzi: {', '.join(f'{k}: {v}' for k, v in sorted(t['eval_status'].items())) or '—'}; "
          f"oczekujące: {t['pending_evals']}; porzucone: {t['dropped_evals']}",
          f"- Odrzucone przez walidatory sugestie modelu: "
          f"{', '.join(f'{k}: {v}' for k, v in t['dropped_observations'].items()) or '—'}",
          f"- Błędy wykonania: {len(t['errors'])}"]
    for x in t["errors"][:20]:
        L.append(f"  - {x['at'][:19]} sesja #{x['session_id']} `{x['where']}`: {x['error']}")
    L += ["", "## E. Materiał do rozwoju aplikacji", "",
          "Przypadki do ręcznego przeglądu (`label: unverified`). Pełny kontekst: `cases.jsonl` w eksporcie. "
          "Nie tworzyć z nich testów bez weryfikacji przez człowieka.", ""]
    for c in d["cases"][:100]:
        ctx = c.get("context") or {}
        ob = c.get("observation") or {}
        bits = [f"sesja #{ctx.get('session_id') or c.get('session_id')}"]
        if ctx.get("turn_id"):
            bits.append(f"tura #{ctx['turn_id']}")
        if ob:
            bits.append(f"„{ob.get('span')}” → „{ob.get('fix')}” ({ob.get('category')}, {ob.get('confidence')})")
        if c.get("stt"):
            bits.append(f"„{c['stt'].get('original')}” → „{c['stt'].get('corrected') or '(ponownie)'}”")
        if c.get("quote") or c.get("note"):
            bits.append(f"fragment: „{c.get('quote') or ''}” uwaga: {c.get('note') or '—'}")
        L.append(f"{c['case']}. **{c['type']}** — {c['why']}; " + "; ".join(bits))
    if len(d["cases"]) > 100:
        L.append(f"… i {len(d['cases']) - 100} więcej w `cases.jsonl`.")
    if not d["cases"]:
        L.append("Brak przypadków w tym okresie.")
    return "\n".join(L) + "\n"


# --- pliki ---
def _write(path: Path, text: str) -> Path:
    LL._private(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)                       # atomowo: przerwanie nie zostawia połowy raportu
    os.chmod(path, 0o600)
    return path


def write_report(repo, pack, pid: int, *, days: int | None = 7, session_id: int | None = None,
                 out_dir: Path | None = None) -> Path:
    since = LL.since_days(days) if days and session_id is None else None
    d = build(repo, pack, pid, since=since, session_id=session_id)
    base = out_dir or ((LL.logs_dir(repo) or Path.cwd()) / "reports")
    tag = f"session-{session_id}" if session_id is not None else datetime.now(UTC).strftime("%Y-%m-%d")
    return _write(base / f"p{int(pid)}-learning-report-{tag}.md", render(d, pack))


def redact(text: str, words: list[str]) -> str:
    """Automatyczna redakcja: e-maile, URL, telefony, długie liczby, nazwa profilu i podane słowa.
    NIE gwarantuje usunięcia wszystkich danych osobowych — eksport wymaga ręcznej kontroli."""
    if not isinstance(text, str):
        return text
    text = _EMAIL.sub("[EMAIL]", text)
    text = _URL.sub("[URL]", text)
    text = _PHONE.sub("[PHONE]", text)
    text = _LONGNUM.sub("[NUMBER]", text)
    for w in sorted({w.strip() for w in words if w and len(w.strip()) >= 2}, key=len, reverse=True):
        text = re.sub(rf"(?i)\b{re.escape(w)}\b", "[NAME]", text)
    return text


def _redact_obj(o, words):
    if isinstance(o, str):
        return redact(o, words)
    if isinstance(o, list):
        return [_redact_obj(x, words) for x in o]
    if isinstance(o, dict):
        return {k: _redact_obj(v, words) for k, v in o.items()}
    return o


EXPORT_README = """# Eksport dziennika nauki (format {v})

Pliki:
- `report.md` — raport z nauki dla wybranego okresu/sesji (to samo co `python main.py logs report`).
- `cases.jsonl` — jeden przypadek na linię: `case`, `type`, `why`, `label` (zawsze `unverified`), `context`
  (`session_id`, `turn_id`, `tutor_before`, `utterance`, `input_mode`, `tutor_after`), `observation`
  (`span`, `fix`, `category`, `confidence`, `status`, `drop_reason`, `model`, `prompt_version`), `review`,
  `stt` (`original`, `corrected`, `low_probs`, `stt_s`, `audio_s`), `quote`, `note`, `item`, `error`.
- `summary.json` — liczby z raportu (bez treści wypowiedzi).

Redakcja: {red}. Automatyczna redakcja NIE usuwa wszystkich danych osobowych (np. nazw miejsc, firm, szczegółów
z życia w treści rozmów). **Przejrzyj pliki ręcznie przed udostępnieniem komukolwiek** (także modelowi AI).
Etykiety `unverified`: to materiał do przeglądu, nie prawda — nie twórz z nich testów bez weryfikacji człowieka.
"""


def export(repo, pack, pid: int, *, days: int | None = 30, session_id: int | None = None, redacted: bool = True,
           extra_words: list[str] | None = None, out_dir: Path | None = None) -> Path:
    """Katalog `exports/p<profil>-<znacznik>/` z raportem, przypadkami i podsumowaniem. Tylko ten profil."""
    since = LL.since_days(days) if days and session_id is None else None
    d = build(repo, pack, pid, since=since, session_id=session_id)
    words = [repo.get_profile(pid)["name"], *(extra_words or [])] if redacted else []
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = (out_dir or ((LL.logs_dir(repo) or Path.cwd()) / "exports")) / f"p{int(pid)}-{stamp}"
    LL._private(base)
    dd = _redact_obj(d, words) if redacted else d
    _write(base / "report.md", render(dd, pack))
    _write(base / "cases.jsonl", "".join(json.dumps({"v": CASES_VERSION, **c}, ensure_ascii=False, default=str)
                                         + "\n" for c in dd["cases"]))
    summary = {k: v for k, v in dd.items() if k != "cases"}
    summary["errors"] = {**summary["errors"], "by_category": {c: {kk: vv for kk, vv in v.items() if kk != "examples"}
                                                              for c, v in summary["errors"]["by_category"].items()}}
    summary["technical"] = {**summary["technical"], "errors": len(summary["technical"]["errors"])}
    _write(base / "summary.json", json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    _write(base / "README.md", EXPORT_README.format(v=CASES_VERSION, red="włączona (e-mail, URL, telefon, długie "
                                                    "liczby, nazwa profilu, podane słowa)" if redacted else
                                                    "WYŁĄCZONA — pliki zawierają pełne wypowiedzi"))
    return base
