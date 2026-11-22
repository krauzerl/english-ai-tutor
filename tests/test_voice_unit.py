import numpy as np

from tests.voice_fakes import FakeMic, blocks, tone
from tutor.voice import audio as A
from tutor.voice.stt import is_phantom
from tutor.voice.text import SentenceSplitter, clean_for_speech


def split(chunks, **kw):
    sp, out = SentenceSplitter(**kw), []
    for c in chunks:
        out += sp.feed(c)
    return out, sp.flush()


def test_splitter_waits_for_full_sentence():
    done, rest = split(["Hello the", "re. How are", " you? Fine"])
    assert done == ["Hello there.", "How are you?"] and rest == ["Fine"]


def test_splitter_no_cut_on_abbrev_decimal_initial():
    done, rest = split(["Dr. Smith paid 3.5 pounds. J. K. Rowling wrote it. "])
    assert done == ["Dr. Smith paid 3.5 pounds.", "J. K. Rowling wrote it."] and rest == []


def test_splitter_first_clause_only_once():
    done, _ = split(["Well, that is a really interesting thing to say, and I agree with it. Yes, right. "], first_clause=20)
    assert done == ["Well, that is a really interesting thing to say,", "and I agree with it.", "Yes, right."]


def test_splitter_short_sentence_merges():
    done, _ = split(["Hi. Nice to see you again. "])
    assert done == ["Hi. Nice to see you again."]  # min_chars: krótkie "Hi." nie opóźnia/nie jest samo


def test_clean_for_speech():
    assert clean_for_speech("**Great** job! 😀 `ok`") == "Great job! ok"
    assert clean_for_speech("- one\n- two") == "one two"
    assert clean_for_speech("*** ... ---") == "" and clean_for_speech("   ") == ""


def test_phantom():
    assert is_phantom("Thank you.") and is_phantom("you") and not is_phantom("I like tea")


def run_ep(x, **kw):
    ep, ev = A.Endpointer(**kw), []
    for b in blocks(x):
        ev.append(ep.update(A.rms(b)))
    return ev


def test_endpointer_detects_end_of_speech():
    sil = np.zeros(int(0.5 * A.MIC_SR), np.float32)
    ev = run_ep(np.concatenate([sil, tone(1.0), np.zeros(A.MIC_SR, np.float32)]))
    assert "end" in ev and ev.index("end") > ev.index("speech")
    assert ev[:5] == ["idle"] * 5


def test_endpointer_rejects_click_and_silence():
    click = np.concatenate([np.zeros(8000, np.float32), tone(0.1), np.zeros(2 * A.MIC_SR, np.float32)])
    ev = run_ep(click)
    assert "end" not in ev and "noise" in ev
    assert set(run_ep(np.zeros(A.MIC_SR * 2, np.float32))) == {"idle"}


def test_endpointer_adapts_to_background_noise():
    rng = np.random.default_rng(0)
    hum = (0.02 * rng.standard_normal(3 * A.MIC_SR)).astype(np.float32)  # głośniejsze tło
    ev = run_ep(hum)
    assert "speech" not in ev
    voice = tone(1.0, 0.3) + (0.02 * rng.standard_normal(A.MIC_SR)).astype(np.float32)
    ev = run_ep(np.concatenate([hum, voice, hum]))
    assert "end" in ev


def test_endpointer_max_utterance():
    ev = run_ep(np.concatenate([np.zeros(A.MIC_SR, np.float32), tone(5.0)]), max_utt=2.0)
    assert "end" in ev


def test_listen_auto_returns_audio_with_preroll():
    x = np.concatenate([np.zeros(A.MIC_SR // 2, np.float32), tone(0.8), np.zeros(A.MIC_SR, np.float32)])
    out = A.listen_auto(FakeMic(blocks(x)), A.Endpointer(), timeout=2)
    assert out is not None and 0.8 * A.MIC_SR < len(out) < 1.8 * A.MIC_SR


def test_listen_auto_timeout_and_poll():
    assert A.listen_auto(FakeMic(), A.Endpointer(), timeout=0.05) is None
    assert A.listen_auto(FakeMic(), A.Endpointer(), poll=lambda: True) is None


def test_simsink_gap_accounting():
    t = [0.0]
    s = A.SimSink(clock=lambda: t[0])
    s.start(1000)
    t[0] = 1.0
    s.write(np.zeros(500))  # gra 1.0-1.5
    t[0] = 1.2
    s.write(np.zeros(500))  # w kolejce: kończy 2.0
    t[0] = 2.5
    s.write(np.zeros(500))  # przerwa 0.5
    assert s.first_audio_at == 1.0 and abs(s.underrun_s - 0.5) < 1e-9 and len(s.gaps) == 1
