"""Benchmark STT (B-lite §6): metryki bez modelu i bez nagrań."""
from bench.stt_bench import kept, score, wer

P = [{"id": "e", "kind": "err", "text": "He go to work.", "keep": ["go"]},
     {"id": "o", "kind": "ok", "text": "We discussed it.", "keep": ["discussed"]},
     {"id": "s", "kind": "short", "text": "B", "options": ["am", "is", "are"], "answer": "is"},
     {"id": "n", "kind": "num", "text": "It is at five.", "keep": ["five|5"]}]


def test_wer_and_keep():
    assert wer("he go to work", "he goes to work") == (1, 4)
    assert kept("It is at 5.", "five|5") and not kept("He goes to work", "go")


def test_score_separates_layers():
    h = {"e": {"text": "He goes to work.", "low_probs": ["goes"], "stt_s": 0.5},
         "o": {"text": "We discuss it.", "low_probs": [], "stt_s": 0.6},
         "s": {"text": "Option B.", "low_probs": [], "stt_s": 0.3}}
    r = score(P, h)
    assert r["n"] == 3 and r["error_retention"] == 0.0           # STT „poprawił” błąd ucznia
    assert r["keep"]["ok"] == "0/1"                              # zgubiona końcówka -ed = pozorny błąd ucznia
    assert r["short_answer_ok"] == "1/1" and r["pronunciation"] == "not assessed"
    assert r["misrecognitions_flagged"] == "1/2" and r["low_probs_precision"] == 1.0
