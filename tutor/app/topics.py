"""Generator tematów Quick Chat (lokalny, bez LLM). F7: katalog kategorii (General, Technical/IT, Medical, Business,
Professional) z tematami i scenariuszami roleplay, losowanie w kategorii z dopasowaniem do poziomu.
Starsza lista tematów (`topics_<lang>.yaml`) zostaje dla zgodności: wznowienia i `--chat ID` z wcześniejszych wersji.

Historia tematów: `session.plan_json["topics"]` sesji `kind="chat"` (bez migracji). Im dawniej temat/kategoria była
użyta, tym chętniej wraca; tematy z ostatnich `AVOID_LAST` użyć nie są proponowane, dopóki są inne."""
from __future__ import annotations

import random
import re
from functools import lru_cache
from importlib import resources

import yaml

AVOID_LAST = 12


@lru_cache(maxsize=4)
def catalog(lang: str = "en") -> dict[str, dict]:
    """{topic_id: {id, category, category_pl, pl, q}}."""
    raw = yaml.safe_load((resources.files("tutor.content") / f"topics_{lang}.yaml").read_text(encoding="utf-8"))
    out = {}
    for cat, body in raw["categories"].items():
        for t in body["topics"]:
            out[t["id"]] = {**t, "category": cat, "category_pl": body["pl"]}
    return out


def history(repo, profile_id: int) -> list[str]:
    """Id użytych tematów od najstarszego (także zmiany tematu w trakcie rozmowy)."""
    out = []
    for s in repo.list_sessions(profile_id):
        if s["kind"] == "chat":
            out += [t["id"] for t in repo.get_session_plan(profile_id, s["id"]).get("topics", []) if t.get("id")]
    return out


# --- katalog F7: kategorie × poziomy × tryby ---
LEVELS = ("A1", "A2", "B1", "B2", "C1")
MODES = ("natural", "guided", "roleplay")
CATEGORIES = ("general", "technical", "medical", "business", "professional", "custom")


@lru_cache(maxsize=4)
def chat_catalog(lang: str = "en") -> dict:
    """{"categories": {id: {pl, about_pl}}, "items": {id: temat albo scenariusz}} z `chat_catalog_<lang>.yaml`."""
    raw = yaml.safe_load((resources.files("tutor.content") / f"chat_catalog_{lang}.yaml").read_text(encoding="utf-8"))
    cats, items = {}, {}
    for cid, body in raw["categories"].items():
        cats[cid] = {"id": cid, "pl": body["pl"], "about_pl": body.get("about_pl", "")}
        for kind, key in (("topic", "topics"), ("roleplay", "roleplays")):
            for t in body.get(key, []):
                q = t.get("opener") if kind == "roleplay" else t["q"]
                items[t["id"]] = {**t, "kind": kind, "q": q, "category": cid, "category_pl": body["pl"]}
    return {"categories": cats, "items": items}


def _li(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else LEVELS.index("B1")


def fits(item: dict, level: str) -> bool:
    """Temat pasuje do poziomu, gdy jego zakres obejmuje poziom; dla A1 także tematy od A2 (z prostszym pytaniem),
    bo katalog nie ma osobnych tematów A1. Poziom to orientacja trudności, nie lista dozwolonych słów."""
    lo, hi = (item.get("lv") or ["A1", "C1"])
    return _li(lo) <= max(_li(level), 1) and _li(hi) >= _li(level)


def opener(item: dict, level: str = "B1") -> str:
    """Pierwsza kwestia: prostsza wersja dla A1–A2, jeśli jest."""
    easy = item.get("opener_easy") if item.get("kind") == "roleplay" else item.get("q_easy")
    return easy if easy and _li(level) <= 1 else item["q"]


def suggest(repo, profile_id: int, n: int = 4, seed: int | None = None, lang: str = "en",
            exclude: set[str] = frozenset(), category: str = "general", level: str = "B1",
            mode: str = "natural") -> list[dict]:
    """n tematów z wybranej kategorii (scenariusze tylko w trybie roleplay), dopasowanych do poziomu, najpierw dawno
    nieużywane; tematy z ostatnich `AVOID_LAST` rozmów wracają dopiero, gdy brak innych. `seed` = losowanie od nowa."""
    items = chat_catalog(lang)["items"].values()
    cat = category if category in chat_catalog(lang)["categories"] else "general"
    kind = "roleplay" if mode == "roleplay" else "topic"
    base = [t for t in items if t["category"] == cat and t["kind"] == kind]
    pool = [t for t in base if fits(t, level)] or base
    hist = history(repo, profile_id)
    recent = set(hist[-AVOID_LAST:]) | set(exclude)
    last_use = {tid: i for i, tid in enumerate(hist)}
    rnd = random.Random(seed if seed is not None else random.SystemRandom().random())
    fresh = [t for t in pool if t["id"] not in recent] or [t for t in pool if t["id"] not in exclude] or pool
    fresh.sort(key=lambda t: (last_use.get(t["id"], -1), rnd.random()))
    return fresh[:n]


def get(topic_id: str, lang: str = "en") -> dict | None:
    """Temat z katalogu F7 albo (zgodność: wznowienia, stare CLI) z wcześniejszej listy tematów."""
    return chat_catalog(lang)["items"].get(topic_id) or catalog(lang).get(topic_id)


def custom(text: str) -> dict:
    """Temat wpisany przez ucznia (id=None ⇒ nie wchodzi do rotacji katalogu)."""
    t = " ".join(text.split())[:200]
    name = re.sub(r"\b(my|our)\b", "your", t.rstrip(".!"), flags=re.I)      # perspektywa nauczyciela
    q = t if t.endswith("?") else f"Let's talk about {name}. What do you like or dislike about {name}?"
    return {"id": None, "kind": "topic", "category": "custom", "category_pl": "Własny temat", "pl": t, "q": q}
