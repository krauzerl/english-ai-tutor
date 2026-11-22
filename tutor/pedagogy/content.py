"""Ładowanie i walidacja treści `tutor/content/<lang>/` (04_PEDAGOGY_SPEC §5, §8).

Jedyny moduł `pedagogy/` z I/O (czyta pliki treści spod przekazanej ścieżki).
Kod nie zna słów języka docelowego: wszystko pochodzi z YAML.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
AREAS = ["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
CLOSED_AREAS = ["grammar", "vocabulary", "reading", "listening"]  # zadania zamknięte, ocena deterministyczna
DOMAINS = ["general", "grammar", "conversation", "tech_it", "interview"]
STATUSES = ["draft", "ai_checked", "human_reviewed", "rejected", "suspect"]
ITEM_TYPES = ["mc", "gap", "transform", "translate_pl", "reorder", "reading_mc", "listening_mc",
              "dictation", "open_write", "open_speak"]
MC_TYPES = {"mc", "reading_mc", "listening_mc"}
OPEN_TYPES = {"open_write", "open_speak"}
PRODUCTIVE_TYPES = {"gap", "transform", "translate_pl", "reorder", "dictation"}
CORE_CATEGORIES = ["tense", "aspect", "agreement", "article", "determiner", "preposition", "word_order",
                   "word_choice", "collocation", "morphology", "register", "spelling", "punctuation",
                   "capitalization", "omission", "l1_calque"]
PROMPTS = ["turn_eval", "rubric_eval", "report_narrative", "gen_item", "solve_item"]
_PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://|\b\d{3}[ -]?\d{3}[ -]?\d{3}\b")


def content_root() -> Path:
    return Path(__file__).resolve().parent.parent / "content"


def norm(s: str) -> str:
    """Normalizacja do porównań: wielkość liter, białe znaki, apostrof typograficzny."""
    return " ".join(s.replace("’", "'").lower().split())


def norm_answer(s: str) -> str:
    """Jak `norm`, plus pomija interpunkcję końcową i wewnętrzną poza apostrofem."""
    s = norm(s)
    s = re.sub(r"[^\w\s']", " ", s)
    return " ".join(s.split())


# --- modele ---
class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Skill(_M):
    id: str
    lang: str
    domain: Literal["general", "grammar", "conversation", "tech_it", "interview"]
    area: Literal["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
    cefr: Literal["A1", "A2", "B1", "B2", "C1", "C2"]
    can_do_pl: str = Field(min_length=5)
    prereqs: list[str] = []
    error_categories: list[str] = []
    target_patterns: list[str] = []
    explanation_ref: str | None = None
    tags: list[str] = []

    @model_validator(mode="after")
    def _patterns(self):
        for p in self.target_patterns:
            re.compile(p)
        return self


class Provenance(_M):
    source: Literal["ai_generated", "human"]
    model: str | None = None
    prompt_version: str | None = None
    created_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _date(cls, v):  # PyYAML zamienia 2026-11-30 na date
        if isinstance(v, dict) and v.get("created_at") is not None:
            v = {**v, "created_at": str(v["created_at"])}
        return v


class Review(_M):
    status: Literal["draft", "ai_checked", "human_reviewed", "rejected", "suspect"] = "draft"
    reviewer: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _date(cls, v):
        if isinstance(v, dict) and v.get("reviewed_at") is not None:
            v = {**v, "reviewed_at": str(v["reviewed_at"])}
        return v

    @model_validator(mode="after")
    def _human(self):
        if self.status == "human_reviewed" and not (self.reviewer and self.reviewed_at):
            raise ValueError("human_reviewed wymaga reviewer i reviewed_at")
        return self


class Item(_M):
    id: str
    lang: str
    skill_ids: list[str] = Field(min_length=1)
    area: Literal["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
    type: Literal["mc", "gap", "transform", "translate_pl", "reorder", "reading_mc", "listening_mc",
                  "dictation", "open_write", "open_speak"]
    cefr: Literal["A1", "A2", "B1", "B2", "C1", "C2"]
    difficulty: float = Field(ge=-1, le=1)
    pools: list[Literal["diagnosis", "practice", "retention"]] = Field(min_length=1)
    domain: Literal["general", "grammar", "conversation", "tech_it", "interview"]
    prompt: str = Field(min_length=3)
    stimulus: str | None = None          # tekst do czytania (reading_mc)
    options: list[str] | None = None
    answers: list[str] | None = None
    explanation_pl: str | None = None
    audio_text: str | None = None        # listening: tekst dla TTS
    provenance: Provenance
    review: Review

    @property
    def productive(self) -> bool:
        return self.type in PRODUCTIVE_TYPES or self.type in OPEN_TYPES


class ErrorCategory(_M):
    id: str
    explanation_pl: str
    l1: str                  # L1: sygnał, bez poprawki
    l2_pl: str               # L2: podpowiedź metajęzykowa
    l3: str | None = None    # L3: elicytacja; brak = wybór z dwóch opcji (szablon `choice_template`)
    l1_pl_note: str | None = None  # L1: uwaga o interferencji z polskim (opcjonalna)


class Errors(_M):
    choice_template: str
    categories: list[ErrorCategory]

    def ids(self) -> set[str]:
        return {c.id for c in self.categories}


class VariantGroup(_M):
    id: str
    kind: Literal["spelling", "lexical", "grammar", "contraction"]
    forms: list[str] = Field(min_length=2)
    note_pl: str | None = None
    skip_domains: list[str] = []


class Variants(_M):
    groups: list[VariantGroup] = []


class Confusables(_M):
    sets: list[list[str]] = []        # to/too/two
    droppable: list[str] = []         # a/an/the: wstawienie lub brak
    suffixes: list[str] = []          # s, ed, 'll, 'd, 've
    pairs: list[list[str]] = []       # can/can't


class Disfluency(_M):
    fillers: list[str]
    filler_phrases: list[str] = []
    restart_markers: list[str] = []


class Criterion(_M):
    id: str
    description_pl: str
    example_phrases: list[str] = Field(min_length=1)


class Scenario(_M):
    id: str
    lang: str
    cefr: Literal["A1", "A2", "B1", "B2", "C1", "C2"]
    domain: Literal["general", "grammar", "conversation", "tech_it", "interview"]
    title_pl: str
    role: str
    goal: str
    success_criteria: list[Criterion] = Field(min_length=3, max_length=5)
    target_skill_ids: list[str] = []
    provenance: Provenance
    review: Review


class Reviewer(_M):
    id: str
    name: str


class Reviewers(_M):
    reviewers: list[Reviewer] = []


class _Bkt(_M):
    p_init: float | None = None
    p_learn: float
    p_slip: float
    p_guess: float | Literal["options"]


class Rubric(_M):
    rubric_version: str
    severity_weights: dict[int, float]
    grammar_vocab: dict[str, Any]
    naturalness: dict[str, Any]
    communication: dict[str, Any]
    fluency: dict[str, Any]
    evidence: dict[str, Any]
    descriptions_pl: dict[str, dict[int, str]]
    classify: dict[str, Any]
    confidence: dict[str, Any]
    bkt: dict[str, _Bkt]
    mastery: dict[str, Any]
    retention: dict[str, Any]
    srs: dict[str, Any]
    diagnosis: dict[str, Any]
    correction: dict[str, Any]
    errors: dict[str, Any]
    planner: dict[str, Any]
    report: dict[str, Any]
    limits: dict[str, Any]


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)  # (area, cefr, status) -> n
    n_skills: int = 0
    n_items: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


class ContentError(Exception):
    def __init__(self, report: Report):
        self.report = report
        super().__init__("; ".join(report.errors[:5]))


@dataclass
class Pack:
    lang: str
    root: Path
    skills: dict[str, Skill]
    items: dict[str, Item]
    errors: Errors
    variants: Variants
    confusables: Confusables
    disfluency: Disfluency
    rubric: Rubric
    scenarios: dict[str, Scenario]
    reviewers: Reviewers
    prompts: dict[str, dict[str, str]]  # name -> {version, text}
    item_files: dict[str, tuple[Path, int]] = field(default_factory=dict)  # id -> (plik, nr linii)


# --- czytanie YAML z numerami linii ---
def _read_list(path: Path, rep: Report) -> list[tuple[int, dict]]:
    """Lista wpisów z numerem linii; brak pliku = pusta lista."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        node = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        rep.errors.append(f"{path.name}: niepoprawny YAML: {e}")
        return []
    if node is None:
        return []
    if not isinstance(data, list):
        rep.errors.append(f"{path.name}: oczekiwano listy")
        return []
    return [(n.start_mark.line + 1, d) for n, d in zip(node.value, data, strict=True)]


def _read_map(path: Path, rep: Report) -> dict:
    if not path.exists():
        rep.errors.append(f"brak pliku {path.name}")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        rep.errors.append(f"{path.name}: niepoprawny YAML: {e}")
        return {}
    if not isinstance(data, dict):
        rep.errors.append(f"{path.name}: oczekiwano mapy")
        return {}
    return data


def _model(cls, data, where: str, rep: Report):
    try:
        return cls.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            rep.errors.append(f"{where}: {loc}: {err['msg']}")
    except TypeError as e:
        rep.errors.append(f"{where}: {e}")
    return None


def _split_front(text: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _load_pack(lang: str, root: Path, rep: Report) -> Pack:
    base = root / lang

    def lst(cls, path, key):
        out = {}
        for line, d in _read_list(path, rep):
            ident = d.get("id") if isinstance(d, dict) else "?"
            obj = _model(cls, d, f"{path.relative_to(root)}:{line} [{ident}]", rep)
            if obj is None:
                continue
            if obj.id in out:
                rep.errors.append(f"{path.relative_to(root)}:{line}: zdublowane id {obj.id}")
            out[obj.id] = obj
        return out

    skills: dict[str, Skill] = {}
    for f in sorted((base / "skills").glob("*.yaml")):
        for k, v in lst(Skill, f, "skills").items():
            if k in skills:
                rep.errors.append(f"{f.name}: zdublowane id {k}")
            skills[k] = v

    items: dict[str, Item] = {}
    item_files: dict[str, tuple[Path, int]] = {}
    for f in sorted((base / "items").glob("*/*.yaml")):
        for line, d in _read_list(f, rep):
            iid = d.get("id") if isinstance(d, dict) else "?"
            it = _model(Item, d, f"{f.relative_to(root)}:{line} [{iid}]", rep)
            if it is None:
                continue
            if it.id in items:
                rep.errors.append(f"{f.relative_to(root)}:{line}: zdublowane id {it.id}")
            items[it.id] = it
            item_files[it.id] = (f, line)

    def one(cls, name, default=None):
        d = _read_map(base / name, rep)
        return _model(cls, d, name, rep) if d else default

    errors = one(Errors, "errors.yaml") or Errors(choice_template="{a} / {b}", categories=[])
    variants = one(Variants, "variants.yaml", Variants())
    confus = one(Confusables, "stt_confusables.yaml", Confusables())
    disf = one(Disfluency, "disfluency.yaml") or Disfluency(fillers=[])
    rubric = one(Rubric, "rubric.yaml")
    reviewers = one(Reviewers, "reviewers.yaml", Reviewers())

    scenarios = {}
    for f in sorted((base / "scenarios").glob("*.yaml")):
        d = _read_map(f, rep)
        sc = _model(Scenario, d, f"scenarios/{f.name}", rep) if d else None
        if sc:
            scenarios[sc.id] = sc

    prompts: dict[str, dict[str, str]] = {}
    for name in PROMPTS:
        p = base / "prompts" / f"{name}.md"
        if not p.exists():
            rep.errors.append(f"brak promptu prompts/{name}.md")
            continue
        meta, body = _split_front(p.read_text(encoding="utf-8"))
        ver = meta.get("prompt_version")
        if not isinstance(ver, str) or not re.fullmatch(rf"{name}\.v\d+", ver):
            rep.errors.append(f"prompts/{name}.md: prompt_version musi mieć postać {name}.vN")
            continue
        prompts[name] = {"version": ver, "text": body}

    return Pack(lang, base, skills, items, errors, variants, confus, disf, rubric, scenarios, reviewers,
                prompts, item_files)  # type: ignore[arg-type]


# --- graf prerekwizytów ---
def find_cycle(skills: dict[str, Skill]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def dfs(n: str) -> list[str] | None:
        state[n] = 1
        stack.append(n)
        for p in skills[n].prereqs:
            if p not in skills:
                continue
            if state.get(p) == 1:
                return stack[stack.index(p):] + [p]
            if p not in state and (c := dfs(p)):
                return c
        stack.pop()
        state[n] = 2
        return None

    for n in skills:
        if n not in state and (c := dfs(n)):
            return c
    return None


# --- warianty i odpowiedzi ---
def _variant_forms(variants: Variants, domain: str | None = None) -> list[list[str]]:
    return [[norm_answer(f) for f in g.forms] for g in variants.groups if domain not in g.skip_domains]


def expand_answers(answers: list[str], variants: Variants, domain: str | None = None) -> set[str]:
    """Wszystkie akceptowane odpowiedzi znormalizowane + warianty z `variants.yaml` (RQ-3.10, T-PED-8).

    Każda grupa wariantów zastępuje formę najwyżej raz na odpowiedź (kończy się też dla „have got”/„have”).
    """
    groups = _variant_forms(variants, domain)
    out = {norm_answer(a) for a in answers}
    todo = [(a, frozenset()) for a in out]
    while todo:
        a, used = todo.pop()
        for gi, g in enumerate(groups):
            if gi in used:
                continue
            for f in g:
                if f" {f} " not in f" {a} ":
                    continue
                for f2 in g:
                    if f2 == f:
                        continue
                    n = " ".join(f" {a} ".replace(f" {f} ", f" {f2} ", 1).split())
                    if n not in out:
                        out.add(n)
                        todo.append((n, used | {gi}))
    return out


def answer_ok(item: Item, response: str, variants: Variants) -> bool:
    """Deterministyczna ocena zadania zamkniętego. Zadania otwarte nie są oceniane tutaj."""
    if item.type in OPEN_TYPES or not item.answers:
        raise ValueError(f"zadanie {item.id} nie jest oceniane deterministycznie")
    return norm_answer(response) in expand_answers(item.answers, variants, item.domain)


# --- statusy i pule ---
def usable(item: Item, purpose: str, allow_unreviewed_practice: bool) -> bool:
    """Brama statusów (§5.3). `placement` = wstępne dopasowanie (nie diagnoza CEFR)."""
    s = item.review.status
    if s in ("draft", "rejected", "suspect"):
        return False
    if purpose in ("diagnosis", "retention", "cefr_check"):
        return s == "human_reviewed"
    if purpose == "practice":
        return s == "human_reviewed" or (s == "ai_checked" and allow_unreviewed_practice)
    if purpose == "placement":
        return s in ("human_reviewed", "ai_checked")
    raise ValueError(purpose)


def select_items(pack: Pack, *, pool: str, purpose: str, allow_unreviewed_practice: bool = True,
                 area: str | None = None, skill_id: str | None = None,
                 exclude: set[str] = frozenset()) -> list[Item]:
    """Zadania z puli spełniające bramę statusów. `retention` nigdy nie wchodzi w `practice` (walidator)."""
    return [i for i in pack.items.values()
            if pool in i.pools and i.id not in exclude and (area is None or i.area == area)
            and (skill_id is None or skill_id in i.skill_ids)
            and usable(i, purpose, allow_unreviewed_practice)]


def diagnosis_gate(pack: Pack, area: str, min_per_level: int) -> dict:
    """Brama T-CONTENT-2: ≥ N zadań `human_reviewed` w puli diagnosis na poziom A1–C1."""
    per = {lv: sum(1 for i in pack.items.values()
                   if i.area == area and i.cefr == lv and "diagnosis" in i.pools
                   and i.review.status == "human_reviewed") for lv in CEFR_LEVELS[:5]}
    return {"area": area, "per_level": per, "open": all(n >= min_per_level for n in per.values())}


def retention_gaps(pack: Pack, need: int, need_productive: int) -> list[str]:
    """Umiejętności bez wystarczającej puli `retention` (sygnał „za mało treści” dla autora)."""
    by_skill: dict[str, list[Item]] = defaultdict(list)
    for i in pack.items.values():
        if "retention" in i.pools and i.review.status == "human_reviewed":
            for s in i.skill_ids:
                by_skill[s].append(i)
    return sorted(s for s in pack.skills
                  if len(by_skill[s]) < need or sum(i.productive for i in by_skill[s]) < need_productive)


# --- walidacja ---
def _check_item(it: Item, pack: Pack, rep: Report, where: str) -> None:
    def err(msg):
        rep.errors.append(f"{where} [{it.id}]: {msg}")

    if not it.id.startswith(f"{pack.lang}."):
        err(f"id bez prefiksu {pack.lang}.")
    if it.lang != pack.lang:
        err("lang różny od pakietu")
    for s in it.skill_ids:
        if s not in pack.skills:
            err(f"nieznane skill_id {s}")
        elif pack.skills[s].area != it.area:
            err(f"obszar zadania {it.area} różny od obszaru umiejętności {s} ({pack.skills[s].area})")
    if "retention" in it.pools and "practice" in it.pools:
        err("pule retention i practice muszą być rozłączne")
    if it.type in OPEN_TYPES:
        pass
    elif not it.answers:
        err("brak akceptowanej odpowiedzi")
    if it.type in MC_TYPES:
        if not it.options or len(it.options) < 2 or len(set(map(norm, it.options))) != len(it.options):
            err("MC: wymagane ≥2 unikalne opcje")
        elif not it.answers or len(it.answers) != 1 or it.answers[0] not in it.options:
            err("MC: dokładnie 1 klucz, który jest jedną z opcji")
    elif it.options is not None:
        err("opcje tylko dla zadań MC")
    if it.type == "gap" and it.prompt.count("___") != 1:
        err("luka: dokładnie jedno ___ w prompt")
    if it.type == "reading_mc" and not it.stimulus:
        err("reading_mc wymaga stimulus")
    if it.type == "listening_mc" and not it.audio_text:
        err("listening_mc wymaga audio_text")
    if it.type == "dictation" and not it.audio_text:
        err("dictation wymaga audio_text")
    if it.review.status == "human_reviewed":
        ids = {r.id for r in pack.reviewers.reviewers}
        if it.review.reviewer not in ids:
            err("human_reviewed: reviewer spoza reviewers.yaml")
    elif it.review.status in ("draft", "ai_checked") and (it.review.reviewer or it.review.reviewed_at):
        err("draft/ai_checked nie mogą mieć reviewer/reviewed_at (to pola decyzji człowieka)")
    if it.provenance.source == "ai_generated" and not it.provenance.prompt_version:
        err("ai_generated wymaga prompt_version")
    text = " ".join(filter(None, [it.prompt, it.stimulus, it.audio_text, *(it.options or []), *(it.answers or [])]))
    if _PII.search(text):
        err("możliwe dane osobowe (e-mail/URL/telefon)")
    lim = pack.rubric.limits.get("prompt_max_words", {}).get(it.cefr) if pack.rubric else None
    if lim and len(it.prompt.split()) > lim:
        err(f"prompt dłuższy niż {lim} słów dla {it.cefr}")


def validate(lang: str, root: Path | None = None) -> Report:
    pack, rep = _collect(lang, root)
    return rep


def _collect(lang: str, root: Path | None) -> tuple[Pack, Report]:
    root = root or content_root()
    rep = Report()
    if not (root / lang).is_dir():
        rep.errors.append(f"brak katalogu treści {root / lang}")
        raise ContentError(rep)
    pack = _load_pack(lang, root, rep)
    cats = pack.errors.ids()
    for c in sorted(cats):
        if c.split(".")[0] not in CORE_CATEGORIES:
            rep.errors.append(f"errors.yaml [{c}]: kategoria spoza rdzenia {CORE_CATEGORIES[0]}…")
    for core in CORE_CATEGORIES:
        if core not in cats and not any(c.startswith(core + ".") for c in cats):
            rep.warnings.append(f"errors.yaml: brak wpisu dla rdzenia {core}")
    for s in pack.skills.values():
        w = f"skills [{s.id}]"
        if not s.id.startswith(f"{pack.lang}."):
            rep.errors.append(f"{w}: id bez prefiksu {pack.lang}.")
        for p in s.prereqs:
            if p not in pack.skills:
                rep.errors.append(f"{w}: nieznany prereq {p}")
        for c in s.error_categories:
            if c not in cats:
                rep.errors.append(f"{w}: kategoria błędu {c} nie istnieje w errors.yaml")
        if s.explanation_ref and not (pack.root / s.explanation_ref).exists():
            rep.errors.append(f"{w}: brak pliku {s.explanation_ref}")
    if cyc := find_cycle(pack.skills):
        rep.errors.append("graf prerekwizytów ma cykl: " + " -> ".join(cyc))
    seen: dict[str, str] = {}
    for iid, it in pack.items.items():
        f, line = pack.item_files[iid]
        _check_item(it, pack, rep, f"{f.relative_to(root)}:{line}")
        if f.parent.name != it.area or f.stem != it.cefr:
            rep.errors.append(f"{f.relative_to(root)}:{line} [{iid}]: plik powinien być items/{it.area}/{it.cefr}.yaml")
        key = "|".join(norm_answer(x or "") for x in (it.prompt, it.stimulus, it.audio_text))
        if key in seen:
            rep.errors.append(f"{f.relative_to(root)}:{line} [{iid}]: duplikat promptu z {seen[key]}")
        seen[key] = iid
        rep.counts[(it.area, it.cefr, it.review.status)] += 1
    for sc in pack.scenarios.values():
        for s in sc.target_skill_ids:
            if s not in pack.skills:
                rep.errors.append(f"scenarios [{sc.id}]: nieznane skill_id {s}")
        if sc.review.status == "human_reviewed" and sc.review.reviewer not in {r.id for r in pack.reviewers.reviewers}:
            rep.errors.append(f"scenarios [{sc.id}]: reviewer spoza reviewers.yaml")
    for g in pack.variants.groups:
        if len({norm_answer(f) for f in g.forms}) < 2:
            rep.errors.append(f"variants [{g.id}]: mniej niż 2 różne formy")
    rep.n_skills, rep.n_items = len(pack.skills), len(pack.items)
    return pack, rep


def load(lang: str, root: Path | None = None) -> Pack:
    pack, rep = _collect(lang, root)
    if rep.errors:
        raise ContentError(rep)
    return pack


def format_report(rep: Report) -> str:
    lines = [f"umiejętności: {rep.n_skills}, zadania: {rep.n_items}"]
    rows: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for (a, c, s), n in rep.counts.items():
        rows[(a, c)][s] = n
    for (a, c) in sorted(rows, key=lambda k: (AREAS.index(k[0]), CEFR_LEVELS.index(k[1]))):
        lines.append(f"  {a:<10} {c}: " + ", ".join(f"{s}={n}" for s, n in sorted(rows[(a, c)].items())))
    lines += [f"OSTRZEŻENIE: {w}" for w in rep.warnings]
    lines += [f"BŁĄD: {e}" for e in rep.errors]
    lines.append("OK" if rep.ok else f"NIEPOPRAWNE: {len(rep.errors)} błędów")
    return "\n".join(lines)


# --- zapis statusów (jedyne miejsca, które zmieniają treść na dysku) ---
def _patch_item(pack: Pack, item_id: str, mutate) -> None:
    path, _ = pack.item_files[item_id]
    text = path.read_text(encoding="utf-8")
    header = "".join(ln for ln in text.splitlines(keepends=True) if ln.startswith("#"))
    data = yaml.safe_load(text)
    for d in data:
        if d["id"] == item_id:
            mutate(d)
            break
    else:
        raise KeyError(item_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200),
                   encoding="utf-8")
    tmp.replace(path)  # shortcut: komentarze w treści zadań nie przeżywają zapisu (poza nagłówkiem)


def set_review(pack: Pack, item_id: str, status: str, *, reviewer: str, now: str,
               notes: str | None = None) -> None:
    """Ścieżka CZŁOWIEKA (`main.py content review`). Tylko tu powstaje `human_reviewed`."""
    if status not in STATUSES:
        raise ValueError(status)
    if reviewer not in {r.id for r in pack.reviewers.reviewers}:
        raise ValueError(f"reviewer „{reviewer}” nie występuje w reviewers.yaml")

    def mut(d):
        d["review"] = {"status": status, "reviewer": reviewer, "reviewed_at": now, "notes": notes}
    _patch_item(pack, item_id, mut)


def set_ai_check(pack: Pack, item_id: str, status: str, note: str | None = None) -> None:
    """Ścieżka AI (`--solve-check`): nigdy `human_reviewed`, nigdy reviewer/reviewed_at (T-CONTENT-3)."""
    if status not in ("draft", "ai_checked", "rejected"):
        raise ValueError(f"AI nie może ustawić statusu {status}")

    def mut(d):
        d["review"] = {"status": status, "reviewer": None, "reviewed_at": None, "notes": note}
    _patch_item(pack, item_id, mut)


def append_draft(pack: Pack, item: dict) -> str:
    """Dopisuje zadanie z generatora; wymusza ai_generated + draft, niezależnie od wejścia."""
    if item.get("area") not in AREAS or item.get("cefr") not in CEFR_LEVELS:  # ścieżka pliku pochodzi z tych pól
        raise ValueError("niepoprawny area/cefr zadania")
    item = {**item, "provenance": {**item.get("provenance", {}), "source": "ai_generated"},
            "review": {"status": "draft", "reviewer": None, "reviewed_at": None, "notes": None}}
    path = pack.root / "items" / item["area"] / f"{item['cefr']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    header = "".join(ln for ln in text.splitlines(keepends=True) if ln.startswith("#"))
    data = (yaml.safe_load(text) if text else None) or []
    data.append(item)
    path.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200),
                    encoding="utf-8")
    return item["id"]


def set_note(pack: Pack, item_id: str, notes: str | None) -> None:
    """Zmienia tylko notatkę recenzji; status, reviewer i data bez zmian."""
    def mut(d):
        d["review"]["notes"] = notes
    _patch_item(pack, item_id, mut)
