"""Live: prawdziwy Kokoro → prawdziwy Whisper → `lesson.judge`. Whisper pisze cyfry i skróty; pojedyncze słowa bywają
źle rozpoznane — to nie może być liczone jako błąd ucznia."""
import numpy as np
import pytest

from tutor.app import lesson as L
from tutor.pedagogy import content as C
from tutor.voice.tts import MODELS, build_tts

pytestmark = pytest.mark.live
SKILL = "en.gram.to_be_present"


@pytest.mark.parametrize("said,allowed", [("I am twenty-five years old.", {"correct"}),
                                          ("I'm twenty-five years old.", {"correct"}),
                                          ("I is twenty five years old.", {"wrong", "unclear"})])
def test_spoken_answer_is_judged_sensibly(said, allowed):
    if not (MODELS / "kokoro/kokoro-v1.0.int8.onnx").exists():
        pytest.skip("brak modelu kokoro")
    from tutor.voice.stt import WhisperSTT
    pack = C.load("en")
    _, items = L.prepare(pack, SKILL)
    gap = next(i for i in items if i.prompt.startswith("I ___"))
    tts = build_tts("kokoro", "bf_emma", 1.0)
    a = tts.synth(said)
    n = int(len(a) * 16000 / tts.sample_rate)
    a16 = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
    tr = WhisperSTT("small.en", "en").transcribe_detailed(a16)
    assert L.judge(pack, SKILL, gap, L.Answer(tr.text, "voice", tr.low_probs)) in allowed, tr
