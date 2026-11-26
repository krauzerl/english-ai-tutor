# Changelog

Notable changes. The project has no releases yet; versions below are development milestones on `main`.

## Unreleased

### F7 final audit fixes
- **Assessment items:** six F7 items had a second correct option; distractors replaced.
- **Corrections:** BrE/AmE phrase variants still recognised after span minimising ("the team are"); bare plurals,
  plurals after a determiner or a numeral are not errors (uncountable nouns still are); noun number changes are not
  explained as verb endings.
- **Voice:** multiple-choice answers spoken as "option B", "number two", "the second one" are understood.
- **Assessment / progress:** wider cross-area prior so a weak area is not pulled up by strong ones; retention after
  14 days; achievement days follow the local clock.
- **Chat / i18n:** a custom topic typed as a sentence gets a natural opener; Exams screen fully in English;
  `main.py --help`.
- **Bench:** `python -m bench.audit_control` — independent control set (clean, variants, STT, multi-error, held-out).

### F7 quality and product completion
- **Teacher:** ending the session ("No, I want to finish our conversation for now") wins over a new topic; intents
  finish / change topic / skip / repeat / explain / help with counter-examples. Correction policies: relaxed, balanced
  (new default; existing profiles moved from `summary` to `periodic` by migration 008) and intensive; role-play is not
  interrupted. Tense swaps without time context (`have → had`) and corrections without a real word change are
  dropped; agreement pairs and wrong-tense edits get the right category; explanations follow the actual edit.
  The conversation prompt no longer forces praise → question and forbids invented AI experiences; a per-turn style
  note and the guard cut repeated exclamations.
- **Pending assessments:** a conversation ends even when some answers are not assessed yet; they are finished later
  (`--finish-evals`, Home → “Finish assessing”) without double counting; the summary says when it is incomplete.
- **Audio:** speech pace presets slow / normal / fast (0.8 / 0.9 / 1.05, default 0.9; pitch unchanged); exercises
  are read in parts with pauses; uncertain transcripts can be sent, re-recorded or corrected (a correction is never a
  language error). Whisper settings unchanged (measured: no gain from the short-utterance variant).
- **Assessment:** optional quick placement plus a comprehensive six-skill assessment (`--assess`): adaptive grammar,
  vocabulary, reading and listening with a cross-area prior; writing and speaking as evidence only (not ready for
  level scoring). Pause, resume, repeat; profile with history, uncertainty, untested areas and recommendations.
  60 new diagnosis items (AI drafts; 57 passed a blind model check, none human-reviewed).
- **Progress:** estimates from first independent attempts on new items, adjusted for difficulty; hints and repeats
  separate; trends only with enough data; retention after 3 / 7 / 14 days; charts per skill.
- **Weak-spots journal:** utterance, context, fix, category, reliability, date and source; dispute a correction or
  mark it as a speech-recognition error (history kept); practise one category.
- **Interface:** Polish / English per profile (central mechanism for screens and engine messages); progress reset and
  profile deletion with name confirmation and a JSON backup.
- **Achievements:** 100 standard + 50 hidden rules computed from real records, idempotent, never affecting mastery;
  trophy hall with categories, filters, search and secrets.
- **Mascot:** three pixel-art concepts to choose from (name not chosen yet).
- Content pack loads about 6× faster (libyaml).

### Fixed
- Text mode (`--no-audio`) no longer loads Kokoro, PortAudio or any voice model. A core install (`pip install -e .`) is
  enough for text conversations and lessons. `numpy` moved to the core dependencies for this.
- Error category from the model is checked against the edit itself: a lone third-person `-s` change right after a
  subject pronoun ("I usually drinks" → "drink") is stored as `agreement.subject_verb`, not as an irregular past
  form. Observations saved earlier keep their original category.

### Added (Quick Chat)
- Level (automatic from the optional placement, otherwise a cautious A2 with a notice; or A1–C1 by hand, which never
  changes placement or mastery), category (General, Technical/IT, Medical, Business, Professional, custom) and mode
  (natural, guided, role-play). 40 topics and 25 role-play scenarios with CEFR ranges; choices remembered per profile.
- Role-play: Polish scenario context first, the tutor stays in role, language feedback after. The prompt drops the
  "always ask a question" rule in role-play and forbids taking over the learner's role or giving professional advice
  the character would not have (found in a Qwen3 audit: a "patient" suggested a drug).

### Fixed (teacher audit with Qwen3 8B)
- Conversation evaluation runs one utterance at a time (a batch of five took ~30 s and was cancelled by any learner
  activity, so most turns were still unevaluated when the chat ended). The summary waits up to 3 s per pending
  utterance (max 60 s) and says so.
- A topic named in a change request ("Maybe travel") is used instead of a random topic.
- "I don't understand" gets a rephrasing; only an explicit "repeat" allows the same sentence again. The repeat guard
  looks at the last 8 replies.
- Formulaic reactions ("That sounds amazing!") are limited like stock praise.
- Choosing a different topic starts a new chat instead of resuming an older open one.
- GUI screens no longer reload the content pack on every request (~0.7 s each).

### Added
- Local browser GUI (`python main.py --gui`, branch `feat/f7-gui`): Python standard-library HTTP server bound to
  127.0.0.1 with Host, Origin and per-launch token checks. Sessions reuse the CLI engine, so grading, FSRS, mastery gates
  and resume behave the same.
- GUI redesign proposal (branch `feat/f7-ui-redesign`): pixel-art educational RPG look drawn in the browser from
  character arrays (title font, teacher mascot with listening/thinking/speaking states, badges, landscape), readable
  sans-serif text, mission map for lessons, trophy room for achievements. Replaces the two retro variants.
- GUI polish (branch `feat/f7-ui-redesign`): original pixel-art frog mascot (working name Kumka) with seven
  states, plum/ivory palette, voice-first Quick Chat, task-first lessons, start screen ordered by priority, profile
  screen, Polish names for error categories and skills.
- Browser tests with Playwright (`tests/test_browser.py`, 17 flows, optional extra `browser-tests`);
  [docs/TESTING.md](docs/TESTING.md) with a real-microphone acceptance scenario.
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
