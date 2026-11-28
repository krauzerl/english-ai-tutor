# Development notes

Current state of the project for whoever continues development (including a new Claude Code session). Public
information only; private reports and learner data are never committed.

## State (2026-11-28)

`main` contains all milestones up to and including **Conversation UX & Real-time Feedback**: F0–F7 (engine, voice,
GUI, assessment, achievements), Teaching Intelligence B-lite (evidence flow), learning logs, learning from recurring
mistakes, smart speaking corrections, optional Gemini, live corrections. The current priority is **daily use and
collecting learning logs**, not new features. Changes should be driven by what the logs show.

## Defaults that matter

| Item | Where | Value |
|---|---|---|
| Conversation / evaluation model | `tutor/llm/__init__.py` `ROLE_DEFAULTS`, `config.toml` | `qwen3:8b`, `think=false` |
| Evaluation prompt | `tutor/app/turn_eval.py` | `turn_eval.v3` (v5 measured, not deployed) |
| Correction mode | profile `correction_style` | `periodic` ("now and then") |
| Wait for evaluation before a reply | `[conversation] eval_wait_s` | 3.0 s (0 = never) |
| Evaluation batch | `tutor/voice/cli.py` `_eval_service` | 1 utterance |
| Gemini | per profile, Settings → AI Models | off; key in the system keyring |
| LanguageTool | `[languagetool] enabled` | false (experimental) |
| Mastery from conversation | `rubric.yaml` gates | closed: corrections never change mastery |
| `human_reviewed` content | `python main.py content review` | set only by a person; diagnosis and retention use only reviewed items |

## Invariants (enforced by tests — do not break)

- `tutor/pedagogy/` is deterministic and makes no LLM calls; the model observes, code decides.
- Every learner table has `profile_id` with `ON DELETE CASCADE`; migrations are additive.
- Evaluation never runs at the same time as local conversation generation; the learner's turn is stored before it
  is evaluated, so nothing is lost on errors or restarts (`restore_pending`).
- Conversation corrections are suggestions (`verified: false`); disputed observations and spelling from speech do not
  count (`Repo.ignored_observation_ids`).
- Retention checks use new items; remediation checks use items other than the practised ones.
- Audio is never stored; the API key never reaches SQLite, JSON, config, logs or the page.

## Where things are

- Conversation turn: `tutor/voice/conversation.py` (`VoiceTutor.respond`: store turn → bounded evaluation wait →
  feedback note → reply). Session loop and GUI-facing lines: `tutor/voice/cli.py` (`_Live`).
- Evaluation: `tutor/app/eval_queue.py`, `session_service.py`, `eval_runner.py`, `ingest.py` (validators, error log).
- Correction policy: `tutor/pedagogy/correction.py` (`impact`, `select`), `tutor/app/feedback.py` (`directive`,
  `live_lines`, `summary_lines`).
- GUI events: engine prints lines with fixed prefixes; `tutor/gui/runner.py` `classify` turns them into events that
  `tutor/gui/static/app.js` polls every 350 ms (`Korekta #…`, `Ocena #…`, `Omówiono #…`, `Model rozmowy: …`).
- Gemini and fallback: `tutor/llm/route.py` (`Routed`), `tutor/app/ai_models.py`, `tutor/llm/keystore.py`.
- Learning logs: `tutor/app/learnlog.py`, `learning_report.py`; event list in [LEARNING_LOGS.md](LEARNING_LOGS.md).
- Category → practice mapping: `tutor/pedagogy/content.py` `skills_for_category`, `tutor/app/weakspots.py`.

## Working rules

- Test on copies of a learner database (`sqlite3 SRC ".backup COPY"`, then `XDG_DATA_HOME`/`XDG_CONFIG_HOME` pointing
  to a scratch directory). Never write to a real `tutor.db` in experiments.
- Ollama: if the system service is disabled, run `ollama serve` (with `OLLAMA_MODELS` pointing to the model store if
  it is not the default).
- Before committing: `pytest`, `ruff check .`, `python main.py content validate en`; for GUI changes also
  `pytest tests/test_browser.py`; for model-facing changes `pytest -m live`.
- Gemini live tests and benchmarks consume the owner's quota: run them only with explicit consent.
- Branches: work on `rnd/*` or `feat/*`, merge to `main` only after tests and a report; no force pushes.

## Known open items (from the logs and reports)

- Error recall of Qwen3 8B is limited; the tutor model sometimes ignores the recast note or invents personal
  experiences.
- Practice material exists for 20 skills; several error categories (e.g. missing auxiliary, word form, articles
  `extra`) have no matching exercises yet.
- Some GUI texts are Polish in the English interface (Gemini consent notice, planner reasons, explanations without an
  English pattern in `tutor/i18n.py`).
- No content has been reviewed by a human; the benchmark gold standard is unreviewed.
- The voice path has not been tested systematically on other microphones.
