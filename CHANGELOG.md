# Changelog

Notable changes. The project has no releases yet; versions below are development milestones on `main`.

## Unreleased

### Fixed
- Text mode (`--no-audio`) no longer loads Kokoro, PortAudio or any voice model. A core install (`pip install -e .`) is
  enough for text conversations and lessons. `numpy` moved to the core dependencies for this.

### Added
- Local browser GUI (`python main.py --gui`, branch `feat/f7-gui`): Python standard-library HTTP server bound to
  127.0.0.1 with Host, Origin and per-launch token checks. Sessions reuse the CLI engine, so grading, FSRS, mastery gates
  and resume behave the same. Two retro visual variants for the owner to choose from.
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
