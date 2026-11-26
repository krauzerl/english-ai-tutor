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
