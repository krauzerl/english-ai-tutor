"""Generator tematów Quick Chat (lokalny, bez LLM): kategorie na przemian, bez powtórek z ostatnich rozmów.

Historia tematów: `session.plan_json["topics"]` sesji `kind="chat"` (bez migracji). Im dawniej temat/kategoria była
użyta, tym chętniej wraca; tematy z ostatnich `AVOID_LAST` użyć nie są proponowane, dopóki są inne."""
from __future__ import annotations

import random
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


def suggest(repo, profile_id: int, n: int = 4, seed: int | None = None, lang: str = "en",
            exclude: set[str] = frozenset()) -> list[dict]:
    """n tematów z RÓŻNYCH kategorii (o ile starcza), preferując dawno nieużywane. `seed` = losowanie od nowa."""
    cat = catalog(lang)
    hist = history(repo, profile_id)
    recent = set(hist[-AVOID_LAST:]) | set(exclude)
    last_use = {tid: i for i, tid in enumerate(hist)}
    cat_last: dict[str, int] = {}
    for tid, i in last_use.items():
        if tid in cat:
            cat_last[cat[tid]["category"]] = max(cat_last.get(cat[tid]["category"], -1), i)
    rnd = random.Random(seed if seed is not None else random.SystemRandom().random())
    pool = [t for t in cat.values() if t["id"] not in recent] or [t for t in cat.values() if t["id"] not in exclude]
    by_cat: dict[str, list[dict]] = {}
    for t in pool:
        by_cat.setdefault(t["category"], []).append(t)
    # najdawniej użyte kategorie najpierw
    cats = sorted(by_cat, key=lambda c: (cat_last.get(c, -1), rnd.random()))
    picked = [min(by_cat[c], key=lambda t: (last_use.get(t["id"], -1), rnd.random())) for c in cats[:n]]
    rest = [t for t in pool if t not in picked]
    rnd.shuffle(rest)
    return (picked + rest)[:n]


def get(topic_id: str, lang: str = "en") -> dict | None:
    return catalog(lang).get(topic_id)


def custom(text: str) -> dict:
    """Temat wpisany przez ucznia (id=None ⇒ nie wchodzi do rotacji katalogu)."""
    t = " ".join(text.split())[:200]
    q = t if t.endswith("?") else f"Let's talk about this: {t.rstrip('.!')}. What would you like to say about it?"
    return {"id": None, "category": "custom", "category_pl": "Własny", "pl": t, "q": q}
