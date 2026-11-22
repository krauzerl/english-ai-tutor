"""Ocena wypowiedzi (04_PEDAGOGY_SPEC §2): prefiltr, `classify`, walidacja dowodów, oceny wymiarów, działania.

LLM tylko obserwuje; tu kod waliduje i liczy. Zasada nadrzędna: BRAK DOWODU = BRAK OCENY, nigdy błąd ucznia.
Rozróżnienia: wypowiedź POPRAWNA (oceniona, 0 obserwacji) ≠ NIEOCENIONA / PRZERWANA / ODRZUCONA (nie wchodzi do
mianowników i nie jest „poprawna”).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tutor.pedagogy.content import (
    Confusables,
    Disfluency,
    Pack,
    Rubric,
    Skill,
    Variants,
    expand_answers,
    norm,
    norm_answer,
)
from tutor.pedagogy.errors import allowed_categories, core_of, counted_confidences, is_counted
from tutor.pedagogy.fluency import delta_pct
from tutor.pedagogy.schemas import Obs, TurnEval, Use

_TOK = re.compile(r"\S+")
_PUNCT = re.compile(r"^[^\w']+|[^\w']+$")
_LEAD = re.compile(r"^[^\w']+")


def _t(s: str) -> str:
    return _PUNCT.sub("", s.replace("’", "'")).lower()


def _tokens(text: str) -> list[tuple[int, int, str]]:
    """Tokeny bez otaczającej interpunkcji: (początek, koniec, słowo małymi literami); puste pomijamy."""
    out = []
    for m in _TOK.finditer(text):
        raw = m.group()
        core = _PUNCT.sub("", raw)
        if core:
            a = m.start() + len(raw) - len(_LEAD.sub("", raw))
            out.append((a, a + len(core), core.replace("’", "'").lower()))
    return out


# --- prefiltr (§2.7) ---
@dataclass(frozen=True)
class Prefilter:
    text: str
    spans: list[tuple[int, int, str]]           # (start, end, filler|repetition|false_start)
    repairs: list[dict]                         # {bad, good}: udana autonaprawa w jednej wypowiedzi
    marked: str                                 # tekst z [[F:...]] dla TurnEval; `turn.text` nietknięty
    runs: list[tuple[int, int]] = field(default_factory=list)  # pełne ciągi powtórzeń („I I”), do cytatów LLM

    @property
    def n_repairs(self) -> int:
        return len(self.repairs)

    def covered(self, start: int, end: int) -> bool:
        return any(a <= start and end <= b for a, b, _ in self.spans) or any(
            a <= start and end <= b for a, b in self.runs)


def prefilter(text: str, cfg: Disfluency) -> Prefilter:
    toks = _tokens(text)
    spans: list[tuple[int, int, str]] = []
    # wypełniacze
    fillers = set(cfg.fillers)
    for a, b, w in toks:
        if w in fillers:
            spans.append((a, b, "filler"))
    for ph in cfg.filler_phrases:  # tylko jako wtrącenie: po przecinku/na początku i przed przecinkiem/na końcu
        for m in re.finditer(rf"(?:(?<=^)|(?<=,\s)|(?<=^\s))({re.escape(ph)})(?=\s*,|\s*$)", text, re.I):
            spans.append((m.start(1), m.end(1), "filler"))
    # powtórzenia sąsiednich tokenów (zostaje ostatni)
    runs: list[tuple[int, int]] = []
    for (a, b, w), (_a2, b2, w2) in zip(toks, toks[1:], strict=False):
        if w == w2 and w not in fillers:
            spans.append((a, b, "repetition"))
            runs.append((a, b2))
    # fałszywe starty / autonaprawy: <fragment> — <restart>; restart zaczyna się od tego samego słowa
    repairs = []
    markers = sorted(cfg.restart_markers, key=len, reverse=True)
    if markers:
        mre = "|".join(re.escape(m) for m in markers)
        for m in re.finditer(rf"\s*({mre})\s*", text):
            before = text[:m.start()]
            seg_start = max(before.rfind("."), before.rfind("?"), before.rfind("!"), -1) + 1
            frag = [(a, min(b, m.start()), w) for a, b, w in toks
                    if seg_start <= a < m.start() and w not in fillers]
            frag = [t for t, nx in zip(frag, [*frag[1:], None], strict=True) if nx is None or nx[2] != t[2]]
            after_end = re.search(r"[.?!]|(?:" + mre + ")", text[m.end():])
            end = m.end() + after_end.start() if after_end else len(text)
            nxt = [t for t in toks if m.end() <= t[0] and t[1] <= end]
            if frag and nxt and frag[0][2] == nxt[0][2]:
                spans.append((frag[0][0], frag[-1][1], "false_start"))
                repairs.append({"bad": text[frag[0][0]:frag[-1][1]].strip(),
                                "good": text[nxt[0][0]:nxt[-1][1]].strip()})
    spans = sorted(set(spans))
    marked, pos = [], 0
    for a, b, _ in spans:
        if a < pos:
            continue
        marked += [text[pos:a], "[[F:", text[a:b], "]]"]
        pos = b
    marked.append(text[pos:])
    return Prefilter(text, spans, repairs, "".join(marked), runs)


def content_words(text: str, pre: Prefilter) -> int:
    """Liczba słów ucznia bez wypełniaczy/powtórzeń/fałszywych startów (mianownik ocen /100 słów)."""
    return sum(1 for a, b, _ in _tokens(text) if not pre.covered(a, b))


# --- dopasowanie cytatu ---
def find_spans(text: str, span: str) -> list[tuple[int, int]]:
    """Wszystkie wystąpienia `span` w `text` (wielkość liter i białe znaki bez znaczenia)."""
    toks = [re.escape(t) for t in span.replace("’", "'").split()]
    if not toks:
        return []
    return [(m.start(), m.end()) for m in re.finditer(r"\s+".join(toks), text.replace("’", "'"), re.I)]


# --- warianty i podejrzenia STT ---
def is_variant(span: str, fix: str, variants: Variants, domain: str | None = None) -> bool:
    """`expand_answers` sam dopasowuje a/an do podmienionej formy (a flat ↔ an apartment), więc błędny
    rodzajnik („an flat” → „an apartment”) nie jest wariantem, tylko błędem."""
    f = norm_answer(fix)
    return f in expand_answers([span], variants, domain) and f != norm_answer(span)


def _strip_common(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    a, b = a[i:], b[i:]
    j = 0
    while j < min(len(a), len(b)) and a[-1 - j] == b[-1 - j]:
        j += 1
    return (a[:len(a) - j], b[:len(b) - j])


def stt_confusable(span: str, fix: str, c: Confusables) -> bool:
    """Para wrażliwa na rozpoznawanie mowy (§2.5): a/the, końcówki, 'll/'d/'ve, can/can't, to/too/two…"""
    a, b = _strip_common([_t(x) for x in span.split()], [_t(x) for x in fix.split()])
    if not a and not b:
        return False
    if (not a and len(b) == 1 and b[0] in c.droppable) or (not b and len(a) == 1 and a[0] in c.droppable):
        return True
    if len(a) == 1 and len(b) == 1:
        x, y = a[0], b[0]
        if any(x in s and y in s for s in c.sets) or [x, y] in c.pairs or [y, x] in c.pairs:
            return True
        short, long_ = sorted((x, y), key=len)
        return long_.startswith(short) and long_[len(short):] in c.suffixes
    return False


# --- klasyfikacja (§2.3, reguły dosłownie) ---
@dataclass(frozen=True)
class Classified:
    kind: str | None
    status: str                         # valid | dropped
    drop_reason: str | None
    span: str
    fix: str | None
    category: str | None
    severity: int | None
    confidence: str | None
    self_repair: bool = False


def _drop(o: Obs, reason: str) -> Classified:
    return Classified(o.k, "dropped", reason, o.s, o.f, o.c, o.v, o.p)


def classify(o: Obs, text: str, *, input_mode: str, low_prob_words: set[str], pre: Prefilter,
             variants: Variants, confusables: Confusables, taxonomy: set[str], rubric: Rubric,
             domain: str | None = None) -> Classified:
    """Pierwsza pasująca reguła wygrywa. Odrzucone zwracane z `drop_reason` (metryka jakości modelu, F8)."""
    cfg = rubric.classify
    where = find_spans(text, o.s)
    if not where:                                                                    # 1
        return _drop(o, "span_not_found")
    if all(pre.covered(a, b) for a, b in where):                                     # 2
        good = " ".join(r["good"] for r in pre.repairs)
        rep = bool(o.f) and norm_answer(o.f) in norm_answer(good) and o.k == "error"
        return Classified("disfluency", "valid", None, o.s, o.f, o.c, o.v, o.p, self_repair=rep)
    if is_variant(o.s, o.f, variants, domain):                                       # 3
        return Classified("variant", "valid", None, o.s, o.f, o.c, o.v, o.p)
    voice = input_mode == "voice"
    if voice and core_of(o.c) in cfg["voice_dropped_categories"]:                    # 4
        return _drop(o, "category_not_spoken")
    if voice:                                                                        # 5
        words = [_t(w) for w in o.s.split()]
        toks = [_t(w) for w in text.split()]
        edge = bool(words) and (toks[:len(words)] == words or toks[-len(words):] == words)
        if (set(words) & low_prob_words) or stt_confusable(o.s, o.f, confusables) or edge:
            return Classified("stt_suspect", "valid", None, o.s, o.f, o.c, o.v, o.p)
    if o.c not in taxonomy:                                                          # 6
        return _drop(o, "category_not_in_taxonomy")
    if norm(o.f) == norm(o.s):
        return _drop(o, "fix_equals_span")
    if len(o.f) > cfg["fix_max_ratio"] * len(o.s) + cfg["fix_extra_chars"]:
        return _drop(o, "fix_too_long")
    return Classified(o.k, "valid", None, o.s, o.f, o.c, o.v, o.p)                   # 7


# --- dowody pozytywne i komunikatywność ---
@dataclass(frozen=True)
class Positive:
    skill_id: str
    area: str
    quote: str


def validate_positive(u: Use, text: str, *, pre: Prefilter, goals: set[str], skills: dict[str, Skill],
                      input_mode: str, low_prob_words: set[str]) -> tuple[Positive | None, str | None]:
    """`t` (użycie konstrukcji celu) wymaga dosłownego cytatu w formie końcowej; inaczej odrzucone z powodem.
    Dotyczy też `ok` (dowód pozytywny), nie tylko błędów."""
    where = find_spans(text, u.s)
    if not where:
        return None, "span_not_found"
    if u.id not in skills:
        return None, "unknown_skill"
    if u.id not in goals:
        return None, "not_a_goal"
    if all(pre.covered(a, b) for a, b in where):
        return None, "in_disfluency"
    if u.r == "ok" and input_mode == "voice" and (set(_t(w) for w in u.s.split()) & low_prob_words):
        return None, "stt_uncertain"
    return Positive(u.id, skills[u.id].area, u.s), None


def validate_comm(cm: str, cq: str, text: str, pre: Prefilter) -> tuple[str, str | None, str | None]:
    """(etykieta, cytat, powód). ok/partial/fail bez dosłownego cytatu = `na` (brak oceny, nie porażka)."""
    if cm == "na":
        return "na", None, None
    if not cq.strip():
        return "na", None, "no_evidence"
    where = find_spans(text, cq)
    if not where:
        return "na", None, "quote_not_found"
    if all(pre.covered(a, b) for a, b in where):
        return "na", None, "quote_is_disfluency"
    return cm, cq, None


# --- wynik oceny jednej wypowiedzi ---
@dataclass
class UttResult:
    index: int
    eval_status: str                    # evaluated | unrated | aborted | rejected
    observations: list[Classified] = field(default_factory=list)
    positives: list[Positive] = field(default_factory=list)
    negatives: list[Positive] = field(default_factory=list)   # `t` z r=bad (dowód negatywny, zwalidowany)
    comm: str = "na"
    comm_quote: str | None = None
    drops: list[str] = field(default_factory=list)   # powody odrzuceń dowodów (metryka jakości)

    @property
    def rated(self) -> bool:
        return self.eval_status == "evaluated"


def evaluate_batch(ev: TurnEval | None, texts: list[str], *, input_modes: list[str],
                   low_probs: list[set[str]], pack: Pack, goals: set[str], failure: str = "unrated",
                   domain: str | None = None) -> list[UttResult]:
    """Łączy wynik LLM z walidatorami. `ev=None` ⇒ wszystkie wypowiedzi mają status `failure`
    (unrated | aborted | rejected). Wypowiedź bez wpisu w `ev.u` = `unrated`. Wpis z pustym `o` = POPRAWNA."""
    out = []
    by_i: dict[int, object] = {}
    for u in (ev.u if ev else []):
        by_i.setdefault(u.i, u)
    tax = allowed_categories(pack.errors)
    for i, text in enumerate(texts):
        u = by_i.get(i)
        if ev is None or u is None:
            out.append(UttResult(i, failure if ev is None else "unrated"))
            continue
        pre = prefilter(text, pack.disfluency)
        r = UttResult(i, "evaluated")
        for o in u.o:
            c = classify(o, text, input_mode=input_modes[i], low_prob_words=low_probs[i], pre=pre,
                         variants=pack.variants, confusables=pack.confusables, taxonomy=tax,
                         rubric=pack.rubric, domain=domain)
            r.observations.append(c)
            if c.status == "dropped":
                r.drops.append(c.drop_reason)
        for t in u.t:
            pos, why = validate_positive(t, text, pre=pre, goals=goals, skills=pack.skills,
                                         input_mode=input_modes[i], low_prob_words=low_probs[i])
            if pos:
                (r.positives if t.r == "ok" else r.negatives).append(pos)
            elif why:
                r.drops.append(f"t:{why}")
        r.comm, r.comm_quote, why = validate_comm(u.cm, u.cq, text, pre)
        if why:
            r.drops.append(f"cm:{why}")
        out.append(r)
    return out


# --- oceny wymiarów 0–4 (§2.2, §2.8) ---
@dataclass
class UttView:
    """Dane jednej wypowiedzi do oceny sesji (z DB: turn + turn_meta + observation)."""
    text: str
    words: int
    input_mode: str
    eval_status: str
    comm: str
    comm_quote: str | None
    observations: list[dict]            # wiersze observation (kind, status, category, severity, confidence, span)
    positives: list[Positive]


def _band(x: float, table: dict, *, ascending: bool = True) -> int | None:
    """Najwyższa ocena, której próg spełnia `x` (tabela ocena→próg). ascending: x ≤ próg."""
    for score in sorted(table, reverse=True):
        if (x <= table[score]) if ascending else (x >= table[score]):
            return score
    return None


def _insufficient(dim: str, reason: str, ev: dict) -> dict:
    return {"dim": dim, "status": "insufficient_evidence", "score": None, "range": None, "reason": reason,
            "quotes": [], "evidence": ev}


def _text_dim(dim: str, utts: list[UttView], rubric: Rubric) -> dict:
    rated = [u for u in utts if u.eval_status == "evaluated"]
    words, n = sum(u.words for u in rated), len(rated)
    need = rubric.evidence["text_dims"]
    ev = {"words": words, "utterances": n}
    if words < need["min_words"] or n < need["min_utterances"]:
        return _insufficient(dim, "too_little_evidence", ev)
    w = rubric.severity_weights
    cfg = rubric.naturalness if dim == "naturalness" else rubric.grammar_vocab
    dimof = rubric.classify["dimension_of"]
    counted = counted_confidences(rubric)

    def pick(sens: bool) -> list[dict]:
        res = []
        for u in rated:
            for o in u.observations:
                if o["status"] != "valid":
                    continue
                if dim == "naturalness":
                    hit = o["kind"] == "natural"
                else:
                    hit = (o["kind"] == "error" or (sens and o["kind"] == "stt_suspect")) \
                        and dimof.get(core_of(o["category"] or ""), "grammar") == dim
                conf_ok = o["confidence"] in counted or (sens and o["confidence"] == "l")
                if hit and conf_ok:
                    res.append(o)
        return res

    def score(obs: list[dict]) -> int:
        per100 = sum(w[o["severity"] or 1] for o in obs) / words * 100 if dim != "naturalness" \
            else len(obs) / words * 100
        s = _band(per100, cfg["per100_max"])
        s = cfg.get("floor_score", 0) if s is None else s
        if s == 4 and dim != "naturalness":
            cover = {p.skill_id for u in rated for p in u.positives if p.area == dim}
            if len(cover) < cfg["min_structures_for_4"]:
                s = 3
        return s

    a_obs, b_obs = pick(False), pick(True)
    sa, sb = score(a_obs), score(b_obs)
    lo, hi = min(sa, sb), max(sa, sb)
    quotes = list(dict.fromkeys(o["span"] for o in b_obs))[:3]
    if lo < rubric.evidence["quote_required_below"] and len(quotes) < rubric.evidence["min_quotes"]:
        return _insufficient(dim, "no_citation", ev)       # ocena < 4 bez cytatu = brak oceny
    return {"dim": dim, "status": "scored", "score": lo if lo == hi else None, "range": None if lo == hi else [lo, hi],
            "reason": None, "quotes": quotes, "evidence": ev}


def _comm_dim(utts: list[UttView], rubric: Rubric) -> dict:
    lab = [u for u in utts if u.eval_status == "evaluated" and u.comm in ("ok", "partial", "fail") and u.comm_quote]
    ev = {"labeled": len(lab)}
    if len(lab) < rubric.evidence["communication"]["min_labeled"]:
        return _insufficient("communication", "too_little_evidence", ev)
    ratio = sum(u.comm == "ok" for u in lab) / len(lab)
    s = _band(ratio, rubric.communication["ok_ratio_min"], ascending=False)
    quotes = [u.comm_quote for u in lab if u.comm != "ok"][:3]
    return {"dim": "communication", "status": "scored", "score": 0 if s is None else s, "range": None,
            "reason": None, "quotes": quotes, "evidence": ev}


def score_fluency(cur: dict | None, baseline_: dict | None, voice_sessions: int, rubric: Rubric,
                  has_voice: bool = True) -> dict:
    """F tylko z głosu. Względem linii bazowej ucznia; wcześniej wyłącznie metryki surowe (bez oceny)."""
    if not has_voice or cur is None:
        return {"dim": "fluency", "status": "not_applicable", "score": None, "range": None, "reason": "text_only",
                "quotes": [], "evidence": {}, "metrics": None}
    e = rubric.evidence["fluency"]
    ev = {"speech_s": cur["speech_s"], "voice_utterances": cur["utterances"]}
    if cur["speech_s"] < e["min_speech_s"] or cur["utterances"] < e["min_voice_utts"]:
        return {**_insufficient("fluency", "too_little_evidence", ev), "metrics": cur}
    if voice_sessions < e["min_voice_sessions_for_score"] or baseline_ is None:
        return {"dim": "fluency", "status": "metrics_only", "score": None, "range": None,
                "reason": "baseline_not_ready", "quotes": [], "evidence": ev, "metrics": cur}
    f = rubric.fluency
    dt = delta_pct(cur["tempo_wpm"], baseline_["tempo_wpm"])
    dp = delta_pct(cur["long_pauses_per_min"], baseline_["long_pauses_per_min"])
    st = _band(dt, f["tempo_delta_pct_min"], ascending=False) or 1
    sp = _band(dp, f["pause_delta_pct_max"], ascending=True) or 1
    return {"dim": "fluency", "status": "scored", "score": min(st, sp), "range": None, "reason": None, "quotes": [],
            "evidence": ev, "metrics": cur, "tempo_delta_pct": round(dt, 1), "pause_delta_pct": round(dp, 1)}


def score_session(utts: list[UttView], rubric: Rubric, *, fluency: dict | None = None,
                  baseline_: dict | None = None, voice_sessions: int = 0) -> dict[str, dict]:
    voice = any(u.input_mode == "voice" for u in utts)
    return {"grammar": _text_dim("grammar", utts, rubric), "vocabulary": _text_dim("vocabulary", utts, rubric),
            "naturalness": _text_dim("naturalness", utts, rubric), "communication": _comm_dim(utts, rubric),
            "fluency": score_fluency(fluency, baseline_, voice_sessions, rubric, has_voice=voice)}


# --- tabela §2.9: obserwacja / wynik → działanie dydaktyczne ---
def obs_actions(o: dict, rubric: Rubric, *, count_30d: int, utts_30d: int, in_goal: bool,
                in_content_phrase: bool = False, stt_in_category_14d: int = 0) -> list[str]:
    """Działania deterministyczne dla jednej obserwacji (`count_30d` = wystąpienia PRZED tą obserwacją)."""
    e = rubric.errors
    kind, sev = o["kind"], o["severity"] or 1
    if o["status"] != "valid":
        return []
    if kind == "error" and is_counted(o, rubric):
        acts = ["error_log", "bkt_incorrect"]
        if sev >= rubric.correction["sev_min_interrupt"] or count_30d >= e["recurring_count"] or in_goal:
            acts.append("correction_candidate")
        elif count_30d == 0:
            acts.append("report_if_top3")
        if count_30d + 1 >= e["recurring_count"] and utts_30d >= e["recurring_utterances"]:
            acts.append("remedial_task")
        return acts
    if kind == "natural":
        return ["suggestion_natural"] + (["srs_construction"] if in_content_phrase else [])
    if kind == "variant":
        return ["note_variant_intensive"]
    if kind == "stt_suspect":
        return ["no_penalty"] + (["written_task"] if stt_in_category_14d + 1 >= e["stt_suspect_count"] else [])
    if kind == "disfluency":
        return ["fluency_metric_only"]
    return []


def positive_actions() -> list[str]:
    return ["bkt_correct", "srs_construction_good"]


def session_actions(dims: dict[str, dict], rubric: Rubric, *, comm_fail_in_scenario: int = 0,
                    fluency_drop_sessions: int = 0) -> list[str]:
    p = rubric.planner
    acts = []
    if comm_fail_in_scenario >= 1:
        acts.append("clarify_request")
    if comm_fail_in_scenario >= 2:
        acts.append("repeat_scenario_with_phrases")
    for d in ("grammar", "vocabulary"):
        s = dims[d]["score"] if dims[d]["status"] == "scored" else None
        if s is None and dims[d]["range"]:
            s = dims[d]["range"][0]
        if s is not None and s <= p["low_score_threshold"]:
            acts += ["next_lesson_theta_drop", "review_prereqs"]
            break
    if fluency_drop_sessions >= p["fluency_drop_sessions"]:
        acts.append("fluency_exercise")
    if any(v["status"] == "insufficient_evidence" for v in dims.values()):
        acts.append("extend_conversation")
    return acts
