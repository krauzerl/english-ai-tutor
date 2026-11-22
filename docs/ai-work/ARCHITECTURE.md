# ARCHITECTURE

## 1. Zasada
Monolit desktopowy, jeden proces Python 3.12, warstwy z zależnością tylko w dół. Bez serwera HTTP, bez agentów, bez wektorów.

```
ui/ (PySide6)  ──►  app/ (serwisy: SessionService, DiagnosisService, ReviewService)
                         │
          ┌──────────────┼──────────────────┐
          ▼              ▼                  ▼
   pedagogy/        llm/ (providers)     speech/ (stt, tts, audio)
   (czysty Python,   ollama, gemini,      faster-whisper, piper
    bez I/O, bez LLM) usage meter
          │              │
          └──────► store/ (SQLite, repozytoria, migracje)
content/<lang>/ (YAML/JSON: skills, items, scenarios, prompts)
```
`pedagogy/` nie importuje `llm/`, `ui/`, `speech/`. Test architektury to wymusza (TEST_PLAN T-ARCH).

## 2. Struktura katalogów
```
tutor/
  config.py            # ścieżki XDG, ładowanie .env/keyring, ustawienia
  store/
    db.py              # połączenie, WAL, foreign_keys=ON, migracje (PRAGMA user_version)
    migrations/001_init.sql
    repo.py            # repozytoria; KAŻDA metoda przyjmuje profile_id
  pedagogy/
    cefr.py            # poziomy, mapowanie theta↔CEFR
    diagnosis.py       # test adaptacyjny, estymacja, niepewność
    mastery.py         # aktualizacja p(mastery)
    srs.py             # wrapper FSRS
    errors.py          # taksonomia błędów, agregacja
    planner.py         # dobór treści lekcji z budżetem minut
    rubric.py          # rubryki oceny pisania/mówienia
    # moduł 04 dodaje: content.py, schemas.py, assessment.py, fluency.py,
    # correction.py, retention.py, report.py — patrz 04_PEDAGOGY_SPEC §8
  llm/
    base.py            # Protocol LLMProvider, Message, Usage
    ollama.py          # przeniesiona logika z main.py
    gemini.py          # google-genai SDK
    structured.py      # JSON → pydantic, retry 1x
    context.py         # budżet kontekstu, checkpointy
    meter.py           # liczenie tokenów/kosztów, limity
  speech/
    audio.py           # nagrywanie (sounddevice), detekcja ciszy
    stt.py             # faster-whisper
    tts.py             # piper (piper-tts)
  app/                 # orkiestracja, jedyne miejsce łączące warstwy
  ui/                  # widoki, QThreadPool workers
  content/en/{skills.yaml, items/*.yaml, scenarios/*.yaml, prompts/*.md}
bench/                 # benchmark modeli (CLI)
tests/
main.py                # entrypoint GUI; --cli zachowuje obecny tryb tekstowy
```

## 3. Model danych (SQLite)
Wszystkie tabele użytkownika: `profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE`.
```
profile(id, name, target_lang, ui_lang, created_at, goals_json, daily_minutes,
        correction_mode, external_api_consent_at NULL)
skill(id TEXT PK, lang, category, cefr, descriptor, prereq_json)          -- treść, globalna
item(id TEXT PK, lang, skill_id, type, cefr, difficulty, payload_json)    -- bank zadań, globalny
skill_state(profile_id, skill_id, p_mastery, attempts, last_seen, mastered_at, PK(profile_id,skill_id))
competence(profile_id, area, cefr, theta, se, n_items, source, rationale, measured_at)  -- historia
diagnosis_run(id, profile_id, started_at, finished_at, state_json)
attempt(id, profile_id, item_id NULL, skill_id, session_id, correct, score, response, feedback_json, created_at)
error_log(id, profile_id, category, skill_id NULL, example, correction, count, first_seen, last_seen, resolved_at NULL)
vocab(id, profile_id, lang, term, meaning_pl, example, source, UNIQUE(profile_id,lang,term))
srs_card(profile_id, card_type, ref_id, fsrs_json, due_at, PK(profile_id,card_type,ref_id))
session(id, profile_id, kind, planned_minutes, started_at, ended_at, plan_json, model_json)
turn(id, session_id, profile_id, role, text, created_at)                  -- pełny transkrypt lokalny
checkpoint(id, session_id, profile_id, upto_turn_id, summary)
session_summary(session_id PK, profile_id, level, summary_json)           -- level: session|week|month
next_plan(profile_id PK, plan_json, created_at)
llm_usage(id, profile_id NULL, provider, model, role, in_tokens, out_tokens, latency_ms, cost_usd, created_at)
```
Indeksy: `(profile_id, due_at)` na `srs_card`, `(profile_id, category)` na `error_log`.

Migracja 003 (moduł 04, F4): `profile.correction_style`, `allow_unreviewed_practice`; `skill_state.status/verify_due_at/verified_*_at/relapses`; `attempt.source/hint_level`; `error_log.status/severity_max/reopened/example_observation_id`; nowe tabele `observation`, `turn_meta`. Tylko `ADD COLUMN` — przebudowa `profile` w runnerze z `foreign_keys=ON` skasowałaby kaskadowo dane (04_PEDAGOGY_SPEC §7).

## 4. Silnik dydaktyczny (deterministyczny)
**Diagnoza** (`diagnosis.py`, szczegóły 04_PEDAGOGY_SPEC §4.2–4.4): per obszar siatka bayesowska θ ∈ [0.5, 6.5], prior N(2.5, 1.5²), model z odgadywaniem i niskim nachyleniem (trudności nieskalibrowane). Wybór zadania: najbliższa trudność do średniej a posteriori (zachowanie schodkowe). Stop: SD < 0.35 lub 10 zadań (min 5). Wynik: poziom + przedział 80%; sufit „C1 lub wyżej” (bank do C1), podłoga „A1 lub niżej”. P2: IRT 1PL po zebraniu danych.
- grammar, vocabulary, reading, listening (TTS odtwarza tekst): zadania zamknięte, ocena deterministyczna.
- writing: 1–2 zadania otwarte; LLM zwraca `RubricScore{descriptor_id: met|partial|not_met, evidence_quote}`; poziom = najwyższy z ≥70% met. Niepewność oznaczona jako wysoka (ocena modelowa).
- speaking: krótka rozmowa 3 min; rubryka zakresu/poprawności/płynności (słowa/min, pauzy z timestampów Whisper). Wymowa nieoceniana — komunikat.

**Mastery** (`mastery.py`): BKT z parametrami stałymi per źródło dowodu (tabela 04_PEDAGOGY_SPEC §4.6). Opanowane: p≥0.85 i poprawne próby produkcyjne w ≥2 różnych dniach. Trwałość: testy po 7 i 30 dniach (`retention.py`).

**SRS**: `fsrs` (PyPI, MIT). Karty: słowo, konstrukcja, umiejętność opanowana (test trwałości). Ocena 1–4 z poprawności i czasu.

**Planer** (`planner.py`) — wejście: stan profilu, minuty, cele. Kolejność priorytetów:
1. zaległe powtórki FSRS (max 30% czasu),
2. błędy z `count≥3` nierozwiązane,
3. umiejętności „w nauce” (0.3<p<0.85) na poziomie profilu,
4. następna umiejętność z odblokowanymi prerekwizytami na poziomie θ…θ+0.5,
5. test trwałości umiejętności opanowanych ≥7 dni temu.

| Minuty | Powtórki | Wyjaśnienie+ćwiczenia | Rozmowa | Weryfikacja |
|---|---|---|---|---|
| 15 | 4 | 5 | 5 | 1 |
| 30 | 6 | 10 | 12 | 2 |
| 45 | 8 | 15 | 18 | 4 |
| 60 | 10 | 20 | 25 | 5 |

## 5. Warstwa LLM
```python
class LLMProvider(Protocol):
    name: str
    def chat(self, messages: list[Message], *, temperature: float, max_tokens: int) -> Reply: ...
    def stream(self, messages, **kw) -> Iterator[str]: ...
    def health(self) -> bool: ...
# Reply: text, usage(in_tokens, out_tokens, latency_ms)
structured(provider, messages, schema: type[BaseModel]) -> BaseModel  # JSON mode + walidacja + 1 retry
```
- Ollama: `/api/chat`, `format: <json schema>`, `options.num_ctx=8192`, `keep_alive`.
- Gemini: SDK `google-genai`, `response_schema`. Model domyślny do wyboru po benchmarku (kandydaci: aktualne Gemini Flash / Flash-Lite). Cennik i limity w `config` — wartości wpisywane ręcznie i sprawdzane z cennikiem Google przed użyciem; nie zakładać darmowych limitów.
- Role: `conversation` (stream, temperatura 0.7), `evaluation` (temp 0, structured), `generation` (temp 0.4, structured).
- Prompty w `content/<lang>/prompts/*.md` z placeholderami; wersjonowane (`prompt_version` zapisywane w `attempt.feedback_json`).

**Kontekst** (`context.py`): `[system prompt] + [profil ≤300 tok] + [ostatnie podsumowanie ≤300] + [top błędy ≤200] + [cele lekcji ≤200] + [checkpoint ≤300] + [ostatnie tury aż do budżetu]`. Liczenie tokenów: heurystyka znaki/3.5 (shortcut), korekta z `usage` providera.

**Ocena i korekta** (04_PEDAGOGY_SPEC §1–§3): wypowiedź → prefiltr deterministyczny → `evaluation` zwraca zwięzły `TurnEval` (obserwacje z dosłownym cytatem, bez wyjaśnień) → walidatory w `pedagogy/assessment.py` (cytat istnieje, taksonomia, warianty BrE/AmE, sygnały STT) → `observation` → polityka korekty. Kolejka oceny w `app/`: jeden wątek, nigdy równolegle z generowaniem rozmowy, przerywana nową turą ucznia, partie do 5 wypowiedzi. Tryby: `summary` (partie, raport), `periodic` (recast w następnej odpowiedzi, ≤1 korekta/3 tury), `intensive` (ocena przed odpowiedzią, limit 10 s, drabina podpowiedzi L1–L4). Wyjaśnienia PL z szablonów `errors.yaml`.

## 6. Mowa
- `audio.py`: `sounddevice` 16 kHz mono, push-to-talk, detekcja ciszy RMS; brak urządzenia → wyjątek `NoMicrophone` → UI przełącza na tekst.
- `stt.py`: `faster-whisper`, model `small.en` (EN) / `small` (inne), CPU int8 domyślnie, `language` wymuszony, `word_timestamps=True` (płynność). GPU opcjonalnie, gdy LLM = Gemini.
- `tts.py`: Kokoro domyślnie (`bf_emma`, `am_michael`), Piper alternatywnie; modele w `~/.local/share/english-ai-tutor/models/`; regulacja tempa dla słuchania. (Faktyczny kod: `tutor/voice/`, moduł 03.)
- F5 dodaje `WhisperSTT.transcribe_detailed()` (słowa, czasy, prawdopodobieństwa) dla płynności i podejrzeń STT; `transcribe()` bez zmian.
- Brak ffmpeg nie jest potrzebny (audio PCM z sounddevice → numpy).

## 7. Wielojęzyczność
Kod rdzenia nie zawiera słów języka docelowego. Wszystko językowe: `content/<lang>/` (skills/, items/, errors.yaml, variants.yaml, stt_confusables.yaml, disfluency.yaml, rubric.yaml, scenarios/, prompts/, grammar/ — schemat 04_PEDAGOGY_SPEC §5). Dodanie `it`: skills.yaml, items, scenarios, prompts, głos Piper, model Whisper `small`. Taksonomia błędów: część wspólna + rozszerzenia per język (`content/<lang>/errors.yaml`).

## 8. UI/UX (zastępstwo Impeccable)
- Lewy pasek nawigacji (8 widoków), obszar treści, pasek stanu (model, połączenie, mikrofon, zużycie limitu).
- Dashboard: dzisiejszy plan (1 przycisk „Zacznij”), poziomy per obszar z przedziałem niepewności (pasek z zakresem), powtórki do zrobienia, top-3 błędy.
- Konwersacja: wiadomości; korekta jako zwijana linia pod wiadomością ucznia (przekreślenie → poprawka, wyjaśnienie po rozwinięciu); przycisk mikrofonu z trzema stanami (gotowy / nagrywanie / przetwarzanie).
- Jedna czcionka systemowa, 2 rozmiary nagłówków, 1 kolor akcentu, odstępy 8 px grid. Bez animacji poza wskaźnikiem pracy.
- Każdy błąd ma komunikat w języku użytkownika z akcją („Spróbuj ponownie”, „Przełącz na tekst”).

## 9. Konfiguracja i dane
- Dane: `~/.local/share/english-ai-tutor/tutor.db` (XDG_DATA_HOME).
- Konfiguracja: `~/.config/english-ai-tutor/config.toml`; sekrety: `keyring` lub `.env` (chmod 600).
- Zależności docelowe: `PySide6`, `pydantic`, `fsrs`, `faster-whisper`, `piper-tts`, `sounddevice`, `numpy`, `google-genai`, `keyring`, `PyYAML`, `requests`; dev: `pytest`, `pytest-qt`.

## 10. Decyzje odrzucone
| Opcja | Powód |
|---|---|
| RAG / baza wektorowa | dane ucznia są strukturalne; SQL wystarcza |
| Agenci / LangChain | deterministyczny planer prostszy i testowalny |
| Serwer webowy | wymaganie: desktop PySide6 |
| ORM | ~15 tabel, czysty `sqlite3` + repozytoria wystarczy |
| Własny SRS | `fsrs` jest gotowy i lepszy niż SM-2 |
