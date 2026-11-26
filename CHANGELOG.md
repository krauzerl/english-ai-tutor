# Changelog

Notable changes. The project has no releases yet; versions below are development milestones on `main`.

## Unreleased

### Fixed
- Text mode (`--no-audio`) no longer loads Kokoro, PortAudio or any voice model. A core install (`pip install -e .`) is
  enough for text conversations and lessons. `numpy` moved to the core dependencies for this.
- Error category from the model is checked against the edit itself: a lone third-person `-s` change right after a
  subject pronoun ("I usually drinks" → "drink") is stored as `agreement.subject_verb`, not as an irregular past
  form. Observations saved earlier keep their original category.

### Added
- Local browser GUI (`python main.py --gui`, branch `feat/f7-gui`): Python standard-library HTTP server bound to
  127.0.0.1 with Host, Origin and per-launch token checks. Sessions reuse the CLI engine, so grading, FSRS, mastery gates
  and resume behave the same.
- GUI redesign proposal (branch `feat/f7-ui-redesign`): pixel-art educational RPG look drawn in the browser from
  character arrays (title font, teacher mascot with listening/thinking/speaking states, badges, landscape), readable
  sans-serif text, mission map for lessons, trophy room for achievements. Replaces the two retro variants.
- Browser tests with Playwright (`tests/test_browser.py`, optional extra `browser-tests`).
- Profile settings `chat_model` (Qwen3 8B or Bielik 11B, conversation only), `io_mode` (voice or text) and
  `input_device` / `output_device`.

## 2026-11 — product package (`ef8bf5b`)

- Quick Chat with a local topic generator, time limit and correction intensity.
- Standard lessons without mandatory placement; optional placement with provisional results.
- FSRS reviews, weak-spots journal with reliability labels and targeted drills.
- Achievements (separate from skill mastery), learning history, per-profile settings.
- Exam-path architecture with one demo path (Polish 8th-grade English exam, practice only).
- `TutorAPI` service layer for a future GUI.

## 2026-11 — F5 and F6

- Voice-first lessons, intent detection (skip, help, "I don't know"), repeat-question and stock-praise guards.
- Adaptive planning, recurring-error suggestions, correction ladder in conversation.
- Mastery evidence gate: replays, hints and uncertain speech recognition never count toward mastery.

Earlier history: see `git log`.
