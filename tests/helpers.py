"""Pomocniki testowe. UWAGA: `promote` działa WYŁĄCZNIE w pamięci testu i nigdy nie zapisuje statusu na dysk;
nie jest recenzją człowieka (decyzja 6)."""
import random
from dataclasses import dataclass, replace

from tutor.pedagogy import content as C
from tutor.pedagogy.diagnosis import item_b, item_g, p_correct


def promote(pack: C.Pack, status: str = "human_reviewed") -> C.Pack:
    rev = C.Review(status=status, reviewer="test-only" if status == "human_reviewed" else None,
                   reviewed_at="2026-01-01" if status == "human_reviewed" else None)
    return replace(pack, items={k: v.model_copy(update={"review": rev}) for k, v in pack.items.items()})


@dataclass
class FakeItem:
    id: str
    cefr: str
    difficulty: float
    type: str = "mc"
    options: list | None = None
    pools: tuple = ("diagnosis",)

    def __post_init__(self):
        if self.options is None:
            self.options = ["a", "b", "c", "d"]


def bank(per_level: int = 15, levels=("A1", "A2", "B1", "B2", "C1")) -> list[FakeItem]:
    out = []
    for lv in levels:
        for k in range(per_level):
            out.append(FakeItem(f"{lv}.{k}", lv, -1 + 2 * k / (per_level - 1)))
    return out


def simulate(rubric, items, true_theta, seed, mode="verified", always=None):
    """Uczeń odpowiada z prawdopodobieństwem z TEGO SAMEGO modelu co estymator (spójność, nie trafność)."""
    from tutor.pedagogy import diagnosis as D
    rng = random.Random(seed)
    st = {"area": "grammar", "mode": mode, "seed": seed, "asked": [], "elapsed_min": 0.0}
    while D.stop_reason(st, rubric) is None:
        it = D.next_item(st, items, rubric)
        if it is None:
            break
        ok = always if always is not None else rng.random() < p_correct(true_theta, item_b(it, rubric),
                                                                       item_g(it), rubric.diagnosis["slope"])
        st = D.record(st, it, ok, rubric, minutes=0.5)
    return st
