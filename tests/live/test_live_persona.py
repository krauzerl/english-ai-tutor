"""Live (pilot): Qwen3 8B nie zmyśla własnych doświadczeń, gdy uczeń pyta nauczyciela o jego życie.
Wymaga `ollama serve` z qwen3:8b. Próg tolerancji: ≤ 1/8 (przed poprawką 6/20 w pomiarze A/B)."""
import re

import pytest

from tutor.app import quickchat as QC
from tutor.app import topics as T
from tutor.llm.ollama import OllamaProvider
from tutor.voice import audio as A
from tutor.voice.conversation import VoiceTutor

pytestmark = pytest.mark.live
CLAIM = re.compile(r"\bI (?:usually|often|love|like|enjoy|went|go|have been|'ve been|used to|spend|cook|prefer)\b"
                   r"|\bmy (?:weekend|family|friend|favou?rite)", re.I)


class Silent:
    name, voice, sample_rate = "none", "-", 24000

    def synth(self, s):
        import numpy as np
        return np.zeros(10, dtype=np.float32)


def test_tutor_does_not_invent_personal_life(repo):
    llm = OllamaProvider("qwen3:8b", think=False, timeout=300)
    if not llm.health():
        pytest.skip("Ollama nie działa")
    claims = 0
    for k, ask in enumerate(["What do you usually do on weekends?", "Do you like cooking?",
                             "Have you ever been to the mountains?", "What about you?"] * 2):
        pid = repo.create_profile(f"p{k}")
        sid = repo.start_session(pid, "chat")
        repo.add_turn(pid, sid, "assistant", "Let's talk about weekends. What did you do last weekend?")
        repo.add_turn(pid, sid, "user", "I went to the cinema with a friend.")
        repo.add_turn(pid, sid, "assistant", "Nice. Was the film good?")
        t = VoiceTutor(repo, pid, sid, llm, Silent(), A.SimSink(),
                       system=QC.system_prompt(T.custom("Weekends"), "B1", "natural"))
        r = t.respond(ask, input_mode="text")
        claims += bool(CLAIM.search(re.sub(r"[\"“][^\"”]*[\"”]", "", r.reply)))
    assert claims <= 1
