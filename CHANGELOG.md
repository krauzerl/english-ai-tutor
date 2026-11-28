# Changelog

Notable changes. The project has no releases yet; versions below are development milestones on `main`.

## Unreleased

### Integration into `main` (2026-11-28)
- `main` now includes B-lite, learning logs, recurring-mistake lessons, smart speaking corrections, optional Gemini
  and live corrections (fast-forward, no merge conflicts).
- README rewritten for users and developers; new screenshots from a demonstration profile (home, live correction,
  weak spots, AI models); `docs/DEVELOPMENT.md` with the current defaults, invariants and working rules.
- `.gitignore`: learning-log folders and `*.jsonl` exports.
- English GUI: readable names for the preposition lessons and English text for the bored/boring and borrow/lend
  explanations.

### Conversation UX and live feedback (branch `rnd/conversation-ux-feedback`)
- **Greeting:** a new Quick Chat starts with a short greeting composed by the code (varied, not the same as last time,
  "again" for returning learners), a topic intro and one question; resumed chats and role-plays are not re-greeted.
- **Corrections during the conversation:** each learner bubble shows the evaluation status and then the model's
  suggestions (fix, short explanation, weight, "Sugestia modelu", **Kwestionuję** / **Źle usłyszane**) as soon as the
  existing evaluation queue stores them — no second evaluation, no duplicates after a resume or a view rebuild.
- **Spoken correction of serious mistakes in the same reply:** the learner's turn is stored and evaluated before the
  reply, with a bounded wait (`[conversation] eval_wait_s`, default 3.0 s; Qwen3 8B: median 1.8 s per utterance, about 2.2 s in a live conversation). If
  the evaluation is late, the reply is not delayed further and the card appears later; a serious mistake from the
  previous turn is introduced as "about what you said before". Minor mistakes are only shown.
- **Practice for detected mistakes:** explanations and 33 closed tasks (ai_checked, not human-reviewed) for
  prepositions of time, place and dependent prepositions; a general category such as `preposition` maps to its
  subcategories; a parent-only match (e.g. passive voice for a Past Continuous mistake) is no longer offered.
- **Spelling from speech:** spelling/punctuation observations from spoken turns, including old transcripts corrected
  by hand, are hidden from the error journal on read (database rows unchanged).
- **Real model in the conversation:** the header shows the provider and model that actually answered, fallback and
  the evaluation model; the sidebar label now says "Model lokalny".
- **Learning logs:** `log.eval_wait`, `log.eval_live`, new fields in `log.tutor_turn`.

### Optional Gemini API integration (branch `rnd/gemini-integration`)
- **Settings → AI Models (per profile):** hidden Gemini API key field with save/replace/remove, key status, consent
  notice before first use, master switch, separate conversation and evaluation model selectors (Local Qwen3 or a
  Gemini model listed by the API), per-session request limit and local request/token counters. New profiles stay
  local-only; the app works without any key.
- **Key storage:** system secret store via `keyring` (Secret Service), filed under a random per-profile identifier;
  memory-only fallback when no secure store exists. Never in SQLite, JSON, config, URLs, logs or GUI responses.
- **Test API:** lists models that support `generateContent`, then one fixed test prompt to the chosen model; separate
  messages for an invalid key, an unavailable model, limits and connection errors. Never runs on its own.
- **Automatic fallback to local Qwen3** (`tutor/llm/route.py`): one switch per outage, cooldown from `retryDelay` or
  two minutes, session-long pause for a daily quota, key/model problems, missing consent or the session request
  limit; `/gemini` retries manually. Context kept, no duplicated replies or evaluations; invalid Gemini JSON is never
  stored and the utterance is scored once locally. Conversation and evaluation fall back independently.
- **Learning logs:** `log.llm` per model call (provider, model requested/used, latency, first token, prompt version,
  tokens, reason, fallback, status).
- **Bench:** `bench/speaking.py --gemini MODEL --key-profile NAME --max-requests N` (hard cap, no fallback).

### Smart speaking corrections (branch `rnd/teaching-intelligence-b-lite`)
- **Conversation correction policy (default `periodic`):** the weight of a mistake comes from the edit, not from the
  model's confidence. Meaning-changing mistakes (bored/boring, borrow/lend, a few false friends, broken negation) get one
  short correction spoken at the start of the next reply; ordinary grammar mistakes keep the gentle recast every few
  turns; prepositions, articles, word choice, style and spelling never interrupt and go to the end summary. A suspected
  speech-recognition error leads to "Did you mean…?" only when meaning is at stake. `summary` and `intensive` unchanged.
- **The conversation model no longer corrects on its own** (it corrected correct sentences and gave wrong forms):
  system prompt line replaced and a per-reply note on the learner message.
- **Validators:** a category that contradicts the edit is rejected (`category_mismatch`, e.g. "preposition" for
  ", lock → and lock"); -ing/-ed and negation get the right category; regular past with a doubled consonant
  (travelled) is `tense.past_simple`; past → present on a correct sentence is rejected; a corrected transcript counts
  as speech (typos in the correction are not spelling mistakes).
- **Fix:** the recurring count of a mistake was always 1 in the correction choice.
- **Learning log:** event `log.correction` (decision, tier, reason, STT suspicion, `verified: false`).
- **Benchmark:** `bench/cases/speaking_corrections.yaml` (dev/held, unvalidated labels), `python -m bench.speaking`.

### Learning from recurring mistakes (branch `rnd/teaching-intelligence-b-lite`)
- **Lesson from a recurring mistake has stages:** a check without hints *before* the explanation (the control
  result now comes from it, `after_explanation: false`), the explanation, practice with hints (easier tasks first),
  then a test on tasks not used before. Each task result is `independent`, `assisted`, `wrong` or `ambiguous`
  (unsure speech recognition: counted neither way). Interrupting and resuming keeps the stage results.
- **Planner (`goal.choose`):** uses the check, the test, the transfer and whether the mistake came back in
  conversation. It does not repeat the same lesson on the same day, stops after 2 lessons per category in 14 days,
  and 3 days after a successful test offers a **transfer** check on new tasks (retention pool, other context when
  available). A correct result is never treated as lasting improvement; mastery stays locked.
- **Quick Chat:** a short check (2 new closed tasks, voice or text, "skip" to go on) before the conversation when a
  mistake is recurring, at most every 2 days; setting `chat_checks`.
- **Report:** conversation activity per day (minutes, utterances, words, speaking time, suggestions per 100 words,
  self-repairs) labelled as *not* evidence; "Nauka na błędach" with before/after results from real answers; event
  `log.remediation`. Weak-spots journal shows the stage status of each mistake.

### Pilot readiness: learning logs (branch `rnd/teaching-intelligence-b-lite`)
- **Learning logs:** session metadata (models, prompt version, correction mode, level, topic, app version) in
  `session.model_json`; events `log.*` / `report.*` in `app_event` with `session_id` (migration 009, additive); JSONL
  mirror without utterance text in `learning-logs/sessions/`; STT original and corrected transcript, re-records,
  timings; teacher reply timing; errors; session end reason. Switch: setting `learning_log` / `logs on|off`.
- **Reports and export:** `python main.py logs report|export|flag|path|prune|delete`; GUI **Postępy → Raport z
  nauki**; export with automatic redaction (manual review still required) and `cases.jsonl` (all `unverified`).
- **Learner reports:** "Zgłoś problem" during a session (missed mistake, wrong correction, misheard, unclear
  explanation, wrong answer key); optional correct form when disputing a correction; "Wyjaśnienie jest niejasne".
- **Teacher:** when the learner asks about the teacher's life, a per-reply note tells the model it is an AI (it
  invented personal experiences in 6/20 replies before, 1/20 after; role-play unchanged).
- **Fixes:** observations now record the evaluation model (was empty in production); uptake after a correction is
  shown in the weak-spots journal (it was stored but never read); log directories are created 0700 at every level.

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
- **English sessions:** topic name, conversation settings and role-play scenario are shown in English.
- **Documentation:** new README with real screenshots of the application (`docs/screenshots/`), audit measurements
  in `docs/TESTING.md`. F7 merged into `main`.

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
