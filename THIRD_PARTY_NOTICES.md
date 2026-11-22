# Third-party notices

This project does not yet have its own licence (see README). The material below keeps its original licences.

## Teaching content

Content in `tutor/content/` is adapted (paraphrased, with original examples and Polish explanations) from the works
below. Changes were made. The generated, authoritative list with checksums is
[`tutor/content/en/ATTRIBUTION.md`](tutor/content/en/ATTRIBUTION.md); source texts are not included in this repository.

| Work | Authors | Licence |
|---|---|---|
| A Digital Workbook for Beginning ESOL (2018) | Eric Dodson, Davida Jordan, Tim Krause | CC BY 4.0 |
| Green Tea Intermediate English Communication OER (2020) | Eric Dodson, Luciana Diniz, Nanci Leiton | CC BY 4.0 |
| Technical Writing Essentials (2019) | Suzan Last | CC BY 4.0 (non-commercial excerpts and figures excluded) |
| Brehe's Grammar Anatomy (v2) | Steven Brehe | CC BY-SA 4.0 (as stated in the book's own PDF front matter) |
| New General Service List 1.2 | Charles Browne, Brent Culligan, Joseph Phillips | CC BY-SA 4.0 |
| NGSL-Spoken 1.2 | Charles Browne, Brent Culligan | CC BY-SA 4.0 |

Material derived from CC BY-SA works (notably `tutor/content/en/vocab/ngsl.csv` and grammar explanations adapted
from Brehe) must be shared under CC BY-SA 4.0 or a compatible licence. Per-item `license` fields in the content
files record the licence that applies. Original project content and benchmark cases are not covered by a blanket
licence.

Licence texts: <https://creativecommons.org/licenses/by/4.0/>, <https://creativecommons.org/licenses/by-sa/4.0/>.

## Software dependencies (not redistributed)

| Package | Licence |
|---|---|
| requests, google-genai | Apache-2.0 |
| pydantic, PyYAML, fsrs, sounddevice, faster-whisper, onnxruntime | MIT |
| numpy | BSD-3-Clause |
| kokoro-onnx | Licence metadata missing in the package; verify upstream before relying on it |
| piper-tts (optional `piper` extra) | GPL-3.0-or-later |

Licences were taken from installed package metadata on 2026-11-22 and may change; check upstream.

## Models and tools (downloaded by the user, not redistributed)

| Component | Licence |
|---|---|
| Qwen3 8B (default conversation and evaluation model, via Ollama) | Apache-2.0 |
| Bielik 11B v2.3 Instruct (default Polish generation model, via Ollama) | Apache-2.0 |
| Kokoro-82M | Apache-2.0 |
| faster-whisper `small.en` | MIT |
| Piper voices | Each voice has its own licence; check before use |
| LanguageTool (optional, separate local process) | LGPL-2.1-or-later |
