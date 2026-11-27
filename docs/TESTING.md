# Running and testing

How to start the application, run the automated tests, and do the manual checks that automation cannot do
(real microphone and speakers, real model behaviour).

## 1. Start the application

```bash
source .venv/bin/activate
ollama serve            # skip if Ollama already runs as a service
python main.py --gui    # opens http://127.0.0.1:8765/
```

The server listens only on `127.0.0.1`. `Ctrl+C` in the terminal stops it; an unfinished lesson, review or placement
resumes later from the start screen (**Kontynuuj**).

## 2. Automated tests

```bash
pip install -e ".[dev]"
pytest                  # unit, integration and GUI tests with fake models; no Ollama, no audio hardware
ruff check .
```

Browser tests (`tests/test_browser.py`, Playwright + Chromium) are skipped unless Playwright is installed:

```bash
pip install -e ".[browser-tests]"
playwright install chromium        # or set TUTOR_CHROMIUM=/path/to/chrome
pytest tests/test_browser.py
```

They cover: first run and profile creation, switching profiles (data stays separate), every screen without
JavaScript errors, Quick Chat turns, a named topic change ("Maybe travel"), the change-topic button, rebuilding the
session view without losing the transcript, page reload during a session, Ollama not running, a lesson task with a
verdict, pause and resume, a due review, placement start and pause, weak spots, progress, achievements and the
filter, saving settings, keyboard skip link, session controls visible without scrolling at 1280×720, 1366×768,
1440×900 and 1920×1080, and no horizontal scroll at phone width.

The browser tests use a fake model and text mode. They do not test the microphone, the speakers or the quality of
real model answers.

## 3. Manual check with the real model (text mode)

About 15 minutes. Use a test profile.

1. **Quick Chat, text mode.** Pick a topic. Write a sentence with a past-tense mistake
   ("Yesterday I cook pasta"). Then ask the teacher a question ("What is your favourite dish?"). Then write
   "Sorry, I don't understand what you mean." Expected: an answer to your question; after "I don't understand",
   a simpler rephrasing, not the same sentence again.
2. **Named topic change.** Write "Can we talk about something else? Maybe travel." Expected: the topic panel shows
   `travel` and the next question is about travel.
3. **Finish.** Click **Zakończ rozmowę**. Expected: "sprawdzam jeszcze N wypowiedzi…" for a few seconds, then a
   "Do poprawy" list with the mistakes you made (model suggestions; they can be wrong).
4. **Lesson.** Start the recommended mission. Answer one task wrong on purpose. Expected: a hint in the yellow box,
   your own answer shown above it, and the frog in the "Spróbuj jeszcze raz" state. Click **Przerwij i zapisz**,
   go to Start, click **Wróć do lekcji**. Expected: the lesson continues at the same task.

## 3d. Pilot: daily-use test (owner, about 40 minutes)

Use your normal profile: the first start after this update upgrades the database (migration 009, only adds a column)
and makes a backup in `~/.local/share/english-ai-tutor/backups/` first.

**Ollama.** On this computer the models are stored for the system service (`/usr/share/ollama`), and the service is
disabled. Start one of these in a separate terminal and leave it running:

```bash
sudo systemctl start ollama
```

```bash
OLLAMA_MODELS=/usr/share/ollama/.ollama/models ollama serve
```

Check: `ollama list` shows `qwen3:8b`.

1. **Start the GUI.** `cd ~/english-ai-tutor && source .venv/bin/activate && python main.py --gui`. Expected: the
   browser opens `http://127.0.0.1:8765/`, the status bar shows the model.
2. **Text conversation (5 min).** Quick Chat, text mode, level B1, any topic. Make a mistake on purpose
   ("Last weekend I go to the cinema"), ask the teacher "What do you usually do on weekends?", then write
   "Let's stop here". Expected: the teacher says it has no weekends / personal life (no invented experiences);
   at the end a "Do poprawy" list (suggestions, can be wrong).
3. **Voice conversation (5 min).** Same, voice mode: click **Mów**, speak, click again. If the "Czy dobrze
   usłyszałem?" box appears, correct one word and send. Expected: your corrected text appears as your utterance; no
   language mistake is recorded for the misheard word. (The microphone path was not tested on real hardware by the
   author of this change — only with simulated audio.)
4. **Full lesson (10 min).** **Lekcje** → recommended lesson → explanation → all tasks (answer one wrong on purpose)
   → short conversation → **Zakończ**. Expected: hints after a wrong answer, a score, the lesson ends.
5. **Report a wrong correction.** **Słabe strony** → a journal entry → **To była poprawna wypowiedź** → type the
   form you think is right (or leave empty). Expected: the entry is struck out and no longer counted.
   During any session you can also use **Zgłoś problem** (missed mistake, misheard, unclear explanation, wrong
   answer key).
6. **Check the error journal.** **Słabe strony**: every entry has a reliability label ("sugestia modelu",
   "potwierdzony ćwiczeniem kontrolnym", …).
7. **Next-lesson recommendation.** **Lekcje**: the suggested lesson shows *why* it was chosen. After three
   conversations with the same kind of mistake, the suggestion should name that mistake.
8. **Learning report.** **Postępy → Raport z nauki**, or in a terminal:
   `python main.py logs report` (prints the file path; `--days 30` for a month).
9. **Where the logs are.** `python main.py logs path` → `~/.local/share/english-ai-tutor/learning-logs/`
   (`sessions/` JSONL without text, `reports/`, `exports/`). Details and the export format:
   [LEARNING_LOGS.md](LEARNING_LOGS.md).

To give a report to an AI model later: `python main.py logs export --days 14`, read the files in the printed
directory, remove anything private, then share `report.md`, `cases.jsonl` and `README.md` (see LEARNING_LOGS.md).

## 3a. Owner test plan (about 45 minutes)

Use a fresh test profile ("Profile" → new profile) so the results are easy to check.

| # | What | How | Check |
|---|---|---|---|
| 1 | Ubuntu audio check | Section 4a below | You hear the test sound; the recording plays back |
| 2 | First voice conversation | Quick Chat → General English, level Automatyczny, Naturalna rozmowa → **Rozpocznij rozmowę**, voice mode | Section 4 steps 1–5 |
| 3 | Medical English | Level B1, Medical English, Roleplay → pick "Ból w klatce piersiowej" | The scenario card appears; the teacher speaks as the patient; ask about onset, character, radiation, medicines, allergies; ask "What does radiate mean?"; finish; the summary and the note "dotyczy wyłącznie języka" appear |
| 4 | Technical English | Level B1, Technical English / IT, Naturalna rozmowa | Questions stay technical; ask the teacher a Python question; say "Can we talk about cybersecurity?" |
| 5 | Ordinary chat | General English, Rozmowa prowadzona | The teacher offers phrases ("You could say: …") when you get stuck |
| 6 | Full lesson | Lekcje → the recommended mission → answer all tasks, at least one wrong on purpose, then the short conversation, then **Zakończ** | Hint after the wrong answer; the lesson ends with a summary |
| 7 | Error recognition | In any chat say or write "Yesterday I go to work by bus" and "She don't like it" | They appear in "Do poprawy" at the end and later in **Słabe strony** as model suggestions |
| 8 | Progress saved | **Postępy**, **Osiągnięcia**, **Start → Ostatnio** | The sessions from this test are listed under the test profile only |

## 3b. F7 retest (owner, about 60 minutes)
Use your normal profile; nothing is reset. Start with `python main.py --gui`.
1. **Pending assessments:** on Home, if “answers are waiting to be assessed” appears, click *Finish assessing* and
   check the summary of the old conversation (History or the journal).
2. **Ending a conversation:** in Quick Chat say or type “No, I want to finish our conversation for now.” — the tutor
   must say goodbye and show the summary, not start a new topic. Also try “I want to finish my project this week.”
   (the chat must continue).
3. **Naturalness and corrections:** 10 minutes of Quick Chat (balanced corrections). Note: replies ending without a
   question, short corrections or self-correction prompts, no correction of correct sentences (try
   “We have ten paying customers.”). At the end: 3–5 issues with explanations, and a note if assessment is incomplete.
4. **Voice:** Settings → *Speech pace* slow / normal / fast. In a lesson, listen: instruction, task, each option and
   the command are read separately. Answer one-word tasks; when *Did I hear you correctly?* appears, try *Record
   again* and correcting the text.
5. **Assessment:** Assessment → choose areas → *Start assessment*; quit midway, come back, *Resume*. Check the profile
   table (range, evidence, untested areas, recommendations).
6. **Progress and journal:** Progress → “Am I really improving?” (with little data it must say *not enough data*).
   Weak spots → dispute one correction, mark one as a speech error; counts change, history stays.
7. **Language and profile:** Settings → *Interface language* English → screens in English → back to Polish.
   Create a test profile, add a chat, then *Reset progress* and *Delete profile* on that test profile only.
8. **Achievements and mascot:** Achievements → filters, search, *Secrets*. Settings → *Mascot (proposal)* A / B / C;
   choose one concept and one of the names in `docs/ai-work/f7-quality/MASCOT_PROPOSAL.md` (local) or tell us.
CLI equivalents: `--finish-evals`, `--assess [areas]`, `--stt-confirm`, `profile reset|delete NAME --yes`.

## 3c. After the final audit (owner, about 30 minutes, on top of 3b)
Measurements: section 5 below. Before the first start, your database will be
migrated v7 → v8 (a `.bak` copy is written to `~/.local/share/english-ai-tutor/backups/` first).
1. **No correction of correct English:** in Quick Chat type “I watch matches on TV every weekend.”, “Do you take any
   medicines?”, “The team are working hard.” — none may appear as an error in the summary or the journal.
2. **Real errors:** “My brother don't like tomatoes.”, “Yesterday I cook pasta.” — both corrected, explanations fit
   (verb ending / past simple). Dispute any wrong suggestion in Weak spots.
3. **Voice choice in a lesson or assessment:** answer a multiple-choice task by saying “B”, “option B”, “number two”
   or “the second one”. If the app is unsure it must ask again, never mark the answer wrong.
4. **Custom topic:** type a full sentence as your own topic — the tutor should not paste it into “Let's talk about…”.
5. **Assessment with an uneven profile:** run Assessment; if one area is much weaker, its range must not be pulled
   up by the others.
6. **English interface:** Exams screen — no Polish sentences left.
7. **Microphone (still unverified):** sections 4a and 4 below.

## 4a. Ubuntu: microphone and speakers before the app (read-only checks)

These commands only list devices or record and play a short test; they do not change any system setting.

```bash
pactl list short sources          # microphones the system sees
```
```bash
pactl list short sinks            # speakers / headphones
```
```bash
arecord -d 4 -f cd /tmp/mic-test.wav && aplay /tmp/mic-test.wav
```
Say a sentence during the four seconds; you should hear it back. If not, choose the right input and output in
Ubuntu **Settings → Sound** (by hand) and repeat.
```bash
python main.py --voice --list-devices
```
This shows the device names the tutor sees. If the default device is wrong, choose it in the app:
**Ustawienia → Głos i dźwięk → Mikrofon / Głośnik (urządzenie)** and save.

The voice path counts as verified only after this test on your devices.

## 4. Real microphone and speakers (owner acceptance)

Automated tests use a simulated microphone. This scenario needs the real devices. About 15 minutes, quiet room.

Before you start: in **Ustawienia → Głos i dźwięk** choose the microphone and speaker if the system defaults are
wrong, set **Tryb domyślny** to *głosowy*, and save.

| Step | Do | Expect | Note what happened |
|---|---|---|---|
| 1 | Start Quick Chat with any topic, voice mode (checkbox **Tryb tekstowy** off) | The teacher's first question is spoken through the speaker; the frog shows "Mówię…" while it speaks | Time from click to first sound |
| 2 | Click **Mów**, say one sentence, click **Stop** | The button turns red with "Stop" while recording; the frog shows "Słucham…"; your words appear in the conversation | Were your words recognised correctly? |
| 3 | Say a sentence with a mistake, e.g. "Yesterday I go to the shop" | A natural reply; with *na bieżąco* corrections the correct form may appear in the reply | Delay from Stop to the first spoken word |
| 4 | While the teacher is speaking, click the microphone | Speech stops and recording starts (interrupting works) | |
| 5 | Click **Powtórz**, then **Wyjaśnij prościej** | A repetition, then a simpler rephrasing | |
| 6 | Say "Can we talk about music?" | The topic changes to music | |
| 7 | Speak very quietly once, then with background noise once | No invented text; at worst "nie rozpoznano" or a short wrong transcript | Any phantom text? |
| 8 | Click **Zakończ rozmowę** | The correction summary; uncertain recognitions are marked "możliwe, że źle usłyszałem" | |
| 9 | Start a lesson in voice mode, answer two tasks by voice | "Rozpoznano: …" shows what was heard; the verdict matches what you said | |
| 10 | Close the browser tab during a lesson, reopen `http://127.0.0.1:8765/` | The session reappears (or resumes from **Kontynuuj**) | |

Please report: the device names, the times from steps 1 and 3, and every step where the result differed from the
expectation.

## 5. Measurements (author's machine, F7)

Measured on the author's machine with Qwen3 8B in Ollama; your numbers will differ.

| What | Result |
|---|---|
| GUI server start to first HTTP response | 0.23 s; 45 MB RSS; no audio or ONNX libraries loaded |
| Screen data (`/api/home`, `/api/lessons`, …) | first request ~0.7 s (content pack load), then 2–4 ms |
| Session start to first teacher message | ~0.8 s |
| Teacher reply, text mode | typically 3.8 s (1.4–9 s) to the first sentence |
| Evaluation of one utterance | ~1.8 s; a batch of five ~30 s (hence one at a time) |
| SQLite `PRAGMA integrity_check` after audit runs | `ok`, WAL mode |

### F7 teacher benchmark (Qwen3 8B, expectations set by hand, not by the model)
`python -m bench.teacher --out result.json` — 30 sentences (15 correct, 15 with errors), 16 commands, an 8-turn chat.

| | before F7 (`23ae82d`) | after F7 |
|---|---|---|
| false corrections on correct sentences | 0/15 | 0/15 |
| missed errors | 3/15 | 3/15 |
| wrong error category | 7/15 | 3/15 |
| explanation fits the actual error | 1/5 | 5/5 |
| commands recognised (finish, topic, repeat, explain, counter-examples) | 7/16 | 16/16 |
| chat replies ending with a question | 8/8 | 6/8 |
| replies opening with an exclamation | 7/8 | 4/8 |
| stock praise / invented AI experiences | 1 / 1 | 0 / 0 |
| assessment time per answer (median) | 1.0 s | 1.0 s |

Single runs on one machine; chat numbers vary with sampling. "We have ten paying customers." was not falsely corrected
in these runs; the new tense rule makes sure it is dropped when the model does it.

### Final F7 audit (independent control set and measurements)
`python -m bench.audit_control --repeat 3` — 59 utterances written before the measurement: 30 correct sentences,
8 accepted BrE/AmE or register variants, 5 speech-recognition errors (voice mode, uncertain word), 8 single errors,
5 sentences with several errors, plus held-out cases. A report is a false correction when the model flags a
correct sentence, variant or recognition error as a language error.

| | before the audit (`156f572`) | after the audit |
|---|---|---|
| false corrections (correct / variants / STT) | 1/30 · 1/8 · 0/5 | 1/30 · 0/8 · 0/5 |
| errors detected | 15/22 | 14/22 |
| spoken multiple-choice answers accepted (Kokoro → Whisper, 30 recordings) | 5/30 | 19/30 |

Whisper `small.en` on 90 synthetic phrases: 58/90 exact, 61/90 after normalising digits and contractions. The misses
are single words (*am*, *is*, *the*, *B*) and proper names (*Gdańsk*, *Booking.com*); full sentences are almost always
right. Qwen3 results in Ollama vary between server restarts even at temperature 0, so differences of one to three
cases are noise. Two false corrections seen in live chats (*I watch matches* → *a match*, *any medicines* →
*medicine*) are now dropped by deterministic rules with unit tests.

