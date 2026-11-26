"""Ścieżki egzaminacyjne: wspólna architektura (definicja YAML → sekcje → zadania z biblioteki → wyniki → gotowość).

Zasady: (1) brak kopiowania arkuszy — zadania z biblioteki aplikacji; (2) wynik to licznik poprawnych/sprawdzonych,
NIGDY punkty ani „prognoza egzaminu”; (3) gotowość ma jawną wiarygodność i listę ograniczeń; (4) próby są ćwiczeniowe
(`no_mastery`) — ćwiczenie egzaminacyjne nie nadaje opanowania; (5) nowa ścieżka = nowy plik YAML w
`tutor/content/exams/`."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from importlib import resources

import yaml

from tutor.app import ingest
from tutor.app import lesson as L
from tutor.app import lesson_voice as V
from tutor.pedagogy import content as C

MIN_ITEMS_FOR_READINESS = 6         # mniej sprawdzonych zadań w sekcji ⇒ „za mało danych”


class ExamError(Exception):
    pass


def _dir():
    return resources.files("tutor.content") / "exams"


def validate(d: dict) -> list[str]:
    """Spójność definicji (używane w testach i przy ładowaniu)."""
    err = []
    for k in ("id", "name_pl", "lang", "official", "sections", "disclaimer_pl"):
        if k not in d:
            err.append(f"brak pola {k}")
    if not d.get("official", {}).get("sources"):
        err.append("official: brak źródeł")
    ids = [s.get("id") for s in d.get("sections", [])]
    if len(ids) != len(set(ids)):
        err.append("duplikaty sekcji")
    for s in d.get("sections", []):
        if s.get("status") == "no_materials":
            continue
        if not (s.get("area") or s.get("areas")) or not s.get("types") or not s.get("per_session"):
            err.append(f"sekcja {s.get('id')}: niepełna")
    return err


def load_all() -> dict[str, dict]:
    out = {}
    for f in sorted(_dir().iterdir(), key=lambda x: x.name):
        if f.name.endswith(".yaml"):
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            if (e := validate(d)):
                raise ExamError(f"{f.name}: {'; '.join(e)}")
            out[d["id"]] = d
    return out


def get(path_id: str) -> dict:
    p = load_all().get(path_id)
    if p is None:
        raise ExamError(f"Nieznana ścieżka: {path_id}")
    return p


def _areas(s: dict) -> set[str]:
    return set(s.get("areas") or [s["area"]])


def section_items(pack: C.Pack, s: dict, allow: bool) -> list[C.Item]:
    if s.get("status") == "no_materials":
        return []
    return [i for i in pack.items.values() if i.area in _areas(s) and i.type in s["types"] and i.cefr in s["cefr"]
            and "practice" in i.pools and i.answers and C.usable(i, "practice", allow)]


def coverage(pack: C.Pack, path: dict, allow: bool = True) -> list[dict]:
    """Co aplikacja naprawdę potrafi sprawdzić w tej ścieżce (liczba zadań, umiejętności)."""
    out = []
    for s in path["sections"]:
        items = section_items(pack, s, allow)
        out.append({"section": s["id"], "name": s["name_pl"], "items": len(items),
                    "skills": len({k for i in items for k in i.skill_ids}),
                    "status": s.get("status", "ok" if items else "no_materials"), "note": s.get("note_pl")})
    return out


def pick(repo, pack: C.Pack, pid: int, path: dict, allow: bool = True) -> list[tuple[str, C.Item]]:
    """Zestaw na sesję: z każdej sekcji `per_session` zadań, najpierw niewidziane (transfer), potem najdawniej użyte."""
    last: dict[str, str] = {}
    for s in repo.list_skill_states(pid):
        for h in repo.attempt_history(pid, s["skill_id"]):
            if h["item_id"]:
                last[h["item_id"]] = h["created_at"]
    out = []
    for s in path["sections"]:
        pool = sorted(section_items(pack, s, allow), key=lambda i: (i.id in last, last.get(i.id, ""), i.difficulty,
                                                                   i.id))
        out += [(s["id"], i) for i in pool[:s.get("per_session", 0)]]
    return out


def _show(item: C.Item, idx: int, n: int) -> str:
    extra = f"\n{item.stimulus}" if item.stimulus else ""
    return extra + L._show(item, idx, n)


def run(repo, pack: C.Pack, pid: int, sid: int, path: dict, ask: Callable[[C.Item, int], L.Answer | None],
        say: Callable[[str], None], *, now: datetime, speak: Callable[[str], None] | None = None,
        allow: bool = True) -> dict:
    """Sesja ćwiczeń: ekran + (opcjonalnie) głos, odpowiedzi oceniane jak w lekcji (`lesson.judge`), bez podpowiedzi.
    Stan w `session.plan_json["exam"]`: wznowienie nie powtarza zrobionych zadań ani nie nalicza podwójnie."""
    speak = speak or (lambda _t: None)
    plan = repo.get_session_plan(pid, sid) or {}
    st = plan.get("exam") or {"path": path["id"], "items": [(s, i.id) for s, i in pick(repo, pack, pid, path, allow)],
                              "results": [], "finished": False}
    repo.set_session_plan(pid, sid, {**plan, "exam": st})
    done = {r["item"] for r in st["results"]}
    todo = [(s, pack.items[i]) for s, i in st["items"] if i not in done]
    if not todo and not st["results"]:
        say("Brak zadań w tej ścieżce dla Twoich ustawień materiałów.")
        return {"asked": 0, "quit": False, "finished": False}
    if not st["results"]:
        say(f"\n{path['name_pl']}\n{path['disclaimer_pl']}")
        speak("Let's practise for the exam. This is practice, not an official result.")
    total = len(st["items"])
    for sec, it in todo:
        n = len(st["results"])
        say(f"\n[{sec}]" + _show(it, n, total))
        speak(V.task(it, n, total))
        if sec == "listening" and it.audio_text:
            speak(it.audio_text)
            say("(nagranie odtworzone głosem; tekst: " + it.audio_text + ")")
        reasks = 0
        while True:
            a = ask(it, n)
            if a is None:
                repo.set_session_plan(pid, sid, {**repo.get_session_plan(pid, sid), "exam": st})
                return {"asked": len(st["results"]), "quit": True, "finished": False}
            if a.mode == "voice":
                say(L._heard(a))
            v = L.judge(pack, it.skill_ids[0], it, a)
            if v == "unclear" and reasks < L.MAX_REASK:
                reasks += 1
                speak(V.reask(a.text))
                say("Nie jestem pewien, czy dobrze usłyszałem. Powiedz jeszcze raz albo wpisz.")
                continue
            if v in ("help",):
                say("Podczas ćwiczeń egzaminacyjnych nie ma podpowiedzi — odpowiedz najlepiej, jak potrafisz.")
                continue
            break
        res = {"item": it.id, "section": sec, "verdict": v}
        if v in ("correct", "wrong", "unknown"):                  # wynik tylko z pewnych odpowiedzi
            ok = v == "correct"
            ingest.apply_item_attempt(repo, pack, pid, sid, it.id, it.skill_ids[0], ok, source="practice",
                                      dedupe_key=f"exam:{sid}:{it.id}", now=now, response=a.text, hint_level=0,
                                      allow_mastery=False, extra={"exam": path["id"], "section": sec},
                                      n_options=len(it.options) if it.options else None)
            say("✓" if ok else f"✗ Poprawna odpowiedź: {it.answers[0]}")
            speak(V.correct(0) if ok else V.reveal(it))
        else:                                                        # niewiarygodne STT albo „skip”: bez oceny
            say("Zadanie bez oceny (niepewne rozpoznanie albo pominięte).")
        st["results"].append(res)
        repo.set_session_plan(pid, sid, {**repo.get_session_plan(pid, sid), "exam": st})
        if v in ("skip", "finish"):
            return {"asked": len(st["results"]), "quit": v == "finish", "finished": False}
    st["finished"] = True
    repo.set_session_plan(pid, sid, {**repo.get_session_plan(pid, sid), "exam": st})
    sc = [r for r in st["results"] if r["verdict"] in ("correct", "wrong", "unknown")]
    say(f"\nKoniec ćwiczeń: {sum(r['verdict'] == 'correct' for r in sc)}/{len(sc)} poprawnych "
        f"(bez oceny: {len(st['results']) - len(sc)}). To nie jest wynik egzaminu.")
    return {"asked": len(st["results"]), "quit": False, "finished": True}


def history(repo, pid: int, path_id: str | None = None) -> list[dict]:
    out = []
    for s in repo.list_sessions(pid):
        if s["kind"] != "exam":
            continue
        e = repo.get_session_plan(pid, s["id"]).get("exam")
        if not e or (path_id and e["path"] != path_id):
            continue
        sc = [r for r in e["results"] if r["verdict"] in ("correct", "wrong", "unknown")]
        out.append({"session_id": s["id"], "date": s["started_at"], "path": e["path"], "finished": e["finished"],
                    "correct": sum(r["verdict"] == "correct" for r in sc), "scored": len(sc),
                    "unscored": len(e["results"]) - len(sc)})
    return out


def readiness(repo, pack: C.Pack, pid: int, path: dict, allow: bool = True) -> dict:
    """Ocena gotowości = liczby z zapisanych prób + jawne ograniczenia. Bez punktów i bez prognozy wyniku."""
    cov = {c["section"]: c for c in coverage(pack, path, allow)}
    by: dict[str, dict] = {}
    for s in repo.list_sessions(pid):
        if s["kind"] != "exam":
            continue
        e = repo.get_session_plan(pid, s["id"]).get("exam")
        if e and e["path"] == path["id"]:
            for r in e["results"]:
                if r["verdict"] in ("correct", "wrong", "unknown"):
                    d = by.setdefault(r["section"], {"correct": 0, "scored": 0, "distinct": set()})
                    d["scored"] += 1
                    d["correct"] += r["verdict"] == "correct"
                    d["distinct"].add(r["item"])
    sections, limits = [], []
    for s in path["sections"]:
        c, d = cov[s["id"]], by.get(s["id"], {"correct": 0, "scored": 0, "distinct": set()})
        if c["status"] == "no_materials":
            label = "nie sprawdzane przez aplikację"
            limits.append(f"{s['name_pl']}: {s.get('note_pl', 'brak materiałów')}")
        elif d["scored"] == 0:
            label = "nie sprawdzono"
        elif len(d["distinct"]) < MIN_ITEMS_FOR_READINESS:
            label = "za mało danych"
            limits.append(f"{s['name_pl']}: tylko {len(d['distinct'])} różnych zadań (min. {MIN_ITEMS_FOR_READINESS})")
        else:
            label = "wstępny obraz"
        sections.append({"section": s["id"], "name": s["name_pl"], "label": label, "correct": d["correct"],
                         "scored": d["scored"], "distinct_items": len(d["distinct"]), "bank_items": c["items"]})
    limits.append("Biblioteka ćwiczeń jest mała i niezweryfikowana przez człowieka; to nie są zadania CKE.")
    limits.append(path["disclaimer_pl"].strip())
    return {"path": path["id"], "name": path["name_pl"], "sections": sections, "limits": limits,
            "overall": "wstępny obraz" if any(x["label"] == "wstępny obraz" for x in sections) else "za mało danych",
            "official_data_status": path["official"]["status"]}


def render(r: dict) -> list[str]:
    out = [f"{r['name']}", "Gotowość (orientacyjna; liczby z Twoich ćwiczeń, nie punkty egzaminu):"]
    for s in r["sections"]:
        out.append(f"  • {s['name']}: {s['label']} — {s['correct']}/{s['scored']} poprawnych, "
                   f"{s['distinct_items']} różnych zadań (w bazie: {s['bank_items']})")
    out += ["Ograniczenia:", *[f"  - {x}" for x in r["limits"]]]
    return out
