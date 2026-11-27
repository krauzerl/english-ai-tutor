# Learning logs

The tutor keeps a local, private record of how you learn and how the teacher behaves, so that real sessions can be
used later to improve the app. Nothing is sent anywhere: there is no network telemetry, and exports are files you
review and share yourself.

## Where the data lives

```
~/.local/share/english-ai-tutor/          (XDG_DATA_HOME; directory 0700)
├── tutor.db                              SQLite — the source of truth (0600)
├── backups/                              automatic copy before every schema migration
└── learning-logs/                        (0700, created automatically)
    ├── sessions/p<profile>-session-<id>.jsonl   event mirror per session, no utterance text (0600)
    ├── reports/p<profile>-learning-report-<date|session-N>.md
    └── exports/p<profile>-<UTC stamp>/          report.md, cases.jsonl, summary.json, README.md
```

`python main.py logs path` prints the directory. `*.db` files are git-ignored and the data directory is outside the
repository, so learning data cannot be committed by accident. Raw audio is never stored (only the transcript and
timing metadata).

## What is recorded

SQLite already held the learning history; the pilot only adds what was missing.

| question | where |
|---|---|
| session: id, profile id (a number, no personal data), start/end, kind, status | `session` |
| language, level, topic, chat mode, correction mode, models, prompt version, STT/TTS, app version (`0.1.0+<commit>`) | `session.model_json`, event `log.session_start` |
| dialogue: turns in order, role, text or voice, STT low-probability words | `turn` |
| AI corrections: quote, fix, category, confidence (h/m/l), model, prompt version, validator result and reason | `observation` (`status`, `drop_reason`) |
| evaluation status of each utterance (evaluated / unrated / aborted / rejected / dropped) | `turn_meta` |
| correction decision in conversation: observation and turn id, category, model severity, tier (`serious` / `grammar` / `minor`) and the rule that set it, decision (`immediate`, `recast`, `self_repair_prompt`, `ladder`, `ask_stt`, `skipped_stt`, `deferred_summary`, `summary_shown`), STT suspicion, `verified: false` (a model suggestion, never an independently verified error) | event `log.correction`; validator rejections stay in `observation` (`status=dropped`, `drop_reason`, e.g. `category_mismatch`) |
| learner reaction to a correction: disputed, speech-recognition error, restored, optional correct form | `observation_review` (`note`) |
| learner reports (wrong correction, missed mistake, misheard, unclear explanation, wrong answer key) | event `report.*` |
| STT: status (ok, confirmed, corrected, rerecord, empty), recognised text, original and corrected transcript, uncertain words, STT time, audio length | event `log.stt` |
| teacher reply timing (first token, first audio), interruption | event `log.tutor_turn` |
| errors (teacher reply, TTS, STT, session) | event `log.error` |
| topic change | event `log.topic_switch` |
| session end: status, reason (quit, finish_intent, time_up, interrupted, lesson_paused, error), counts, pending/dropped evaluations | event `log.session_end` |
| lessons: attempts, first answers, hints, retries, source (practice, remediation, …) | `attempt` |
| why a lesson was chosen, control-exercise result (confirmed / not_confirmed / inconclusive), uptake after a correction | session plan (`plan_json`: `choice`, `agv`, `uptake`) |
| learning from a recurring mistake: stage of each task (`pre` check before the explanation, `practice`, `post` test on other tasks, `transfer` after a break, `check` at the start of Quick Chat), result of each task (`independent`, `assisted`, `wrong`, `ambiguous`), stage times | session plan (`stages`, `results`, `stage_at`, `cycle`), event `log.remediation` (counts per stage, no text) |
| conversation activity per day: minutes, utterances (voice/text), words per utterance, longest utterance, speaking time (length of accepted recordings), model suggestions per 100 evaluated words, self-repairs visible in the transcript, uptake | computed for the report from `turn`, `turn_meta`, `observation`, `log.stt` (nothing new is stored) |

Events are rows in the existing `app_event` table (kinds `log.*` and `report.*`, with `session_id`; migration 009 only
adds that column and an index). The JSONL mirror contains the same events with IDs, timings and statuses but **no
text**: text fields are replaced by their length (`original_len`, `quote_len`, …). Use the IDs to join with SQLite.

### Labels, not truth

* A correction from the model is a **suggestion**. Only a control exercise confirms a problem (`agv = confirmed`).
* A correction the learner did not dispute is **not** marked correct.
* A missed mistake is recorded only when the learner reports it (`report.missed_error`), and it stays `unverified`.
* Uptake and correct use in conversation are observations; they never set mastery (mastery stays locked).
* A corrected transcript is a speech-recognition correction, never a language error.
* Conversation activity (minutes, words, speaking time, number of suggestions) is **not** evidence of progress.
  Pronunciation is not scored (a transcript does not measure it). An utterance without a correction is not counted
  as correct: Qwen3 misses part of the mistakes.
* Evidence of improvement comes only from closed tasks checked by code: the check before the explanation, the test
  after the lesson on other tasks, the transfer on new tasks after at least 3 days, and the short checks at the start
  of Quick Chat. A task answered after a hint is `assisted`; an answer the speech recogniser was unsure about is
  `ambiguous` and is counted neither way. Most skills have only 3 practice tasks, so a stage often has one task: the
  report marks it "1 zadanie, słaby dowód".

## Commands

```bash
python main.py logs path                                  # where the logs are
python main.py logs report                                # Markdown report, last 7 days (--days N, --session ID)
python main.py logs export                                # redacted export, last 30 days (--days 0 = everything)
python main.py logs export --session 42 --redact-word Kraków
python main.py logs export --no-redact                    # full text, for your own analysis only
python main.py logs flag missed_error --quote "I like play" --note "like playing"
python main.py logs off                                   # stop detailed events (reports are still saved)
python main.py logs on
python main.py logs prune --days 180                      # delete old JSONL files (the database is not touched)
python main.py logs delete --yes                          # delete this profile's log files and log events
```

Add `--profile NAME` before the subcommand to choose a profile (default: the last selected one), for example
`python main.py logs --profile anna report`.

In the browser interface: **Postępy → Raport z nauki** writes and shows the 7-day report; **Słabe strony** has
"To była poprawna wypowiedź" (optionally with the correct form), "To błąd rozpoznania mowy" and "Wyjaśnienie jest
niejasne"; during a session, **Zgłoś problem** saves a report linked to your last utterance or exercise;
**Ustawienia → Szczegółowy dziennik nauki** switches detailed events on or off.

## Report

Sections: A — sessions, time, activities, topics, lessons, and the conversation activity table (labelled "not
evidence of progress"); B — error categories (suggestions, split by confidence),
examples with the utterance, ambiguous cases, recurring problems and their control-exercise result; C — skills
practised with first independent attempts, retries and hints, BKT estimate (not mastery), control exercises, uptake,
why each lesson was chosen, retention on new items, and "Nauka na błędach": per mistake category, the check, practice,
test, transfer and Quick Chat checks with their real results and how often the mistake came back in conversation
after the last check; D — disputed corrections, reports, STT statistics, evaluation
status, validator drops, runtime errors; E — cases for review.

## Export format (version 1)

`exports/p<profile>-<stamp>/`:

* `report.md` — the report above.
* `cases.jsonl` — one case per line: `v`, `case`, `type`, `why`, `label` (always `unverified`), `context`
  (`session_id`, `turn_id`, `turn_index`, `tutor_before`, `utterance`, `input_mode`, `tutor_after`, `at`),
  `observation` (`observation_id`, `kind`, `category`, `span`, `fix`, `confidence`, `status`, `drop_reason`, `model`,
  `prompt_version`), `review` (`verdict`, `note`, `at`), `stt` (`status`, `original`, `corrected`, `low_probs`,
  `stt_s`, `audio_s`), `quote`, `note`, `item` (`item_id`, `answers`, `skill_ids`), `attempt_id`, `error`, `app`.
  Types: `disputed_correction`, `stt_flagged_correction`, `ambiguous_correction`, `stt_suspect`,
  `dropped_suggestion`, `evaluation_incomplete`, `stt_transcript`, `report.<kind>`, `runtime_error`.
* `summary.json` — the report numbers without utterance text.
* `README.md` — this format and the redaction status.

Redaction (default on) replaces e-mail addresses, URLs, phone numbers, long numbers, the profile name and any
`--redact-word` with placeholders. **It does not remove every personal detail** (places, employers, events you talk
about). Read the files before you share them with anyone, including an AI model. Cases are material for review: do
not turn them into regression tests until a person has checked the expected answer.

## Sharing with an AI model for analysis

1. `python main.py logs export --days 14` (add `--redact-word` for names of people, places and employers you used).
2. Open the printed directory, read `report.md` and `cases.jsonl`, delete anything you do not want to share.
3. Give the model `report.md`, `cases.jsonl` and `README.md`, with a request such as: "These are unverified cases from
   my English tutor. For each case, say whether the teacher's correction was right, and propose a regression test
   only for cases you are sure about."

## Retention and deletion

* JSONL files older than 180 days are deleted automatically when a session starts (`logs prune` with another limit).
* The learning history in SQLite is never deleted automatically.
* `logs delete --yes` removes the profile's log files and `log.*`/`report.*` events; lessons, conversations and
  progress stay. Resetting or deleting a profile also removes its log files.
* Turning the detailed log off (`logs off` or the setting) stops new `log.*` events and JSONL lines; learning itself
  is unaffected and learner reports are still saved, because they are explicit actions.

A logging failure (full disk, permissions) is caught and never stops a lesson or a conversation.
