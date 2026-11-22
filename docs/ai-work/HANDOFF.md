# HANDOFF – start implementacji

Audyt zakończony 2026-11-22. Nie powtarzaj go. Czytaj w kolejności: ten plik → REQUIREMENTS → ARCHITECTURE → IMPLEMENTATION_PLAN → TEST_PLAN. AUDIT tylko w razie wątpliwości.
**F3 i F4 wykonane (raporty `05_F3_CONTENT_REPORT.md`, `06_F4_PEDAGOGY_REPORT.md`). Następny krok: F5 (integracja: kolejka oceny, `transcribe_detailed()`, rozmowa) — dopiero po decyzji użytkownika.**

## Stan wyjściowy
- Repo: `main.py` (40 linii, CLI chat z Ollamą), puste `ollama_client.py`, `prompts.py`. Brak testów. Branch `main`, czysty.
- Zachować: wywołanie `/api/chat` z `main.py` → przenieść do `tutor/llm/ollama.py`; `main.py --cli` zachowuje obecne zachowanie. Puste pliki usunąć w F0.
- `.venv` = Python 3.12.3, zawiera tylko `requests`. Instalować zależności do `.venv`, nie do systemowego 3.13 ani anacondy.

## Środowisko — fakty
- Ubuntu 24.04, Ryzen 7 3700X, 31 GiB RAM, RTX 2060 SUPER **8 GiB VRAM**.
- Ollama 0.9.0, serwis w module 03 działał — uruchom `ollama serve` lub poproś użytkownika o `sudo systemctl enable --now ollama`. Modele: `SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M`, `bielik-7b-instruct-v0.1-gguf`.
- Zainstalowane (moduł 03): faster-whisper, kokoro-onnx, piper-tts, sounddevice, onnxruntime (bez torcha). Brak: PySide6, ffmpeg (niepotrzebny); PortAudio z .deb w `~/.local/lib/english-ai-tutor/`. `GEMINI_API_KEY` nieustawiony — użytkownik ma dostęp na rok; poprosić o klucz do `~/.config/english-ai-tutor/.env`, nigdy do repo.
- Whisper uruchamiać na CPU (int8) gdy Bielik 11B na GPU — razem nie mieszczą się w 8 GiB.

## Kluczowe decyzje (nie zmieniać bez powodu)
1. Silnik dydaktyczny `tutor/pedagogy/` czysty, deterministyczny, bez LLM.
2. SQLite + `sqlite3` bez ORM; każda tabela ucznia ma `profile_id` z `ON DELETE CASCADE`.
3. Bez RAG, wektorów, agentów, serwera HTTP.
4. LLM tylko przez `LLMProvider`; odpowiedzi strukturalne walidowane pydantic, 1 retry.
5. Diagnoza: niezależne obszary, wynik z przedziałem niepewności (dopracowane w pkt 11).
6. SRS: biblioteka `fsrs`. Mastery: BKT ze stałymi parametrami.
7. Wymowa poza MVP; nigdy nie twierdzić, że poprawna transkrypcja = poprawna wymowa.
8. Treść językowa wyłącznie w `content/<lang>/`; statusy `draft/ai_checked/human_reviewed/rejected/suspect`; `human_reviewed` tylko przez CLI `content review` (człowiek). Diagnoza i testy trwałości tylko z `human_reviewed`.
9. Zewnętrzne API wymaga zgody per profil; limity kosztów w `config.toml` (cennik wpisuje użytkownik/weryfikuje z Google).
10. LLM obserwuje (cytat, kategoria, pewność), kod liczy oceny, mastery, plan i raport. Żadna liczba dla ucznia nie pochodzi wprost z LLM.
11. Diagnoza: siatka bayesowska per obszar, przedział 80%, sufit „C1 lub wyżej” (bank do C1), symulacje ≠ trafność CEFR.
12. Korekta: 3 tryby `summary/periodic/intensive`; ocena w kolejce, nigdy równolegle z generowaniem rozmowy; brama jakości Bielika w F8.
13. Głos: Kokoro (`bf_emma` domyślny, `am_michael`), Bielik 11B, Whisper `small.en`; transkrypcje tak, nagrania nie; BrE i AmE równorzędne; moduł głosowy bez przebudowy.

## Status
- **F4 ukończone** (gałąź `feat/f4-pedagogy`, wypchnięta, bez scalania): `tutor/pedagogy/*`, `tutor/app/ingest.py`, migracja 003. 246 testów zielone. Decyzje nadrzędne: wstępne dopasowanie z `ai_checked` (nie diagnoza), domyślnie korekta `summary` do benchmarku Bielika, idempotentne zapisy, brak `human_reviewed` bez recenzji. Szczegóły i odstępstwa: `06_F4_PEDAGOGY_REPORT.md`.
- **F3 ukończone** (gałąź `feat/f3-content`, wypchnięta): `tutor/content/en/` (115 umiejętności, 60 zadań pilotażowych: 49 `ai_checked` kontrolą Bielika na ślepo, 11 `draft`, 0 `human_reviewed`), `content validate/review`, `tools/gen_items.py`. Raport: `05_F3_CONTENT_REPORT.md`. Czeka na użytkownika: recenzent treści (brama diagnozy 300 zadań).
- **Moduł 04 (projekt silnika dydaktycznego) ukończony** (gałąź `feat/pedagogy-design` z `113f84e`, wypchnięta; bez scalania do `main`). `04_PEDAGOGY_SPEC.md`: ocena 5 wymiarów (rubryki, dowody, niepewność, błąd vs wariant vs STT vs wypełniacz, ocena → działanie), 3 tryby korekty z drabiną podpowiedzi i ponownym użyciem, kolejka oceny pod Bielika 11B, diagnoza bayesowska z sufitem C1, BKT/FSRS/trwałość 7 i 30 dni, rejestr błędów ze statusami, schemat katalogu i banku, proces weryfikacji treści, raport z dowodów, migracja 003, kryteria odbioru §11. Zaktualizowano REQUIREMENTS, ARCHITECTURE, TEST_PLAN, IMPLEMENTATION_PLAN. Kodu silnika brak (celowo).
- **Moduł 03 (głos) ukończony** (gałąź `feat/voice-prototype`, z `feat/f0-scaffold`): `tutor/voice/`, `python main.py --voice`, raport `03_VOICE_REPORT.md` (uruchomienie, porównanie TTS, benchmark, optymalizacje). STT faster-whisper (CPU int8), TTS Kokoro i Piper za jednym interfejsem. Mediana startu mowy: Piper+small.en 2,64 s, Kokoro+small.en **3,44 s (cel <3 s niespełniony)**, base.en 1,65/2,70 s. **Czeka na użytkownika:** odsłuch próbek (`~/.local/share/english-ai-tutor/voice_samples/`), rozmowa fizyczna, wybór głosu/silnika, BrE/AmE. Wymaga `libportaudio2` i modeli w `~/.local/share/english-ai-tutor/models/` (instrukcja w raporcie). Nagrań nie zapisujemy. Gemini nadal odroczony. Nie scalono do `main`.
- **F2 ukończone** (warstwa LLM, lokalny commit, bez push): `tutor/llm/`, raport `02_LLM_REPORT.md`. Budżet API atomowy (rezerwacje w SQLite, test współbieżności), cennik zero = błąd. Live Ollama wykonane (Bielik 11B ≈11 tok/s z offloadem CPU, 7B ≈64 tok/s; pomiary w raporcie). **Live Gemini ODROCZONE** — wymaga klucza w `~/.config/english-ai-tutor/.env`, `GEMINI_LIVE_MODEL`, limitów i cennika w `config.toml`. Uruchamianie: `.venv/bin/pytest -m live`, pomiar: `PYTHONPATH=. .venv/bin/python tests/live/bench_ollama.py`. Gałąź `feat/f0-scaffold` wypchnięta na origin (krauzerl/english-ai-tutor); `main` nietknięty, PR/scalenie czeka na decyzję. Następny: F3 (treść) lub F4.
- **F0 + F1 ukończone** (gałąź `feat/f0-scaffold`, lokalny commit, bez push). Raport: `01_FOUNDATION_REPORT.md`. Następny: F2 (warstwa LLM) lub F3 (treść) — czeka na akceptację.
- Odstępstwo: tabel `skill`/`item` nie ma w SQLite (treść globalna w `content/`), patrz raport pkt 4. `session_summary` ma własny `id` (nie `session_id` jako PK).
- Uruchamianie: `.venv/bin/pytest`, `.venv/bin/ruff check .`; profile: `python main.py profile ...`. T-ISO-4 zrobiony w F2.

## Pierwsze kroki (F0 → F1) — wykonane
1. Gałąź `feat/f0-scaffold`. Użyj `superpowers:writing-plans` dla F0+F1, potem `test-driven-development`.
2. `pyproject.toml` (Python ≥3.12), pakiet `tutor/`, `tests/`, `pytest`, `ruff`.
3. Migracja `001_init.sql` dokładnie wg ARCHITECTURE §3.
4. Najpierw testy T-ISO-1..4 i T-DB-1..2, potem `repo.py`.
5. Każda faza = PR z DoD z IMPLEMENTATION_PLAN.

## Pytania otwarte do użytkownika
- Czy włączyć serwis Ollamy i zaktualizować ją (wymaga sudo)?
- Klucz Gemini i rzeczywisty plan/limity konta (do `config.toml`).
- Kto przegląda bank zadań (człowiek; brama diagnozy: ≥15 `human_reviewed` na obszar × poziom A1–C1 = 300)? Do tego czasu diagnoza per obszar wyłączona.
- `allow_unreviewed_practice` domyślnie `true` (ćwiczenia z `ai_checked` z etykietą) — potwierdzić.
- Rozstrzygnięte w module 04: BrE i AmE równorzędne (głos domyślny `bf_emma`), nagrania nie są zapisywane.

## Narzędzia
Ponytail (minimalizm), Superpowers (plany, TDD, weryfikacja), Caveman (czat). Impeccable niedostępny — zasady UI w ARCHITECTURE §8. Bezpieczeństwo: `/security-review`, agent `claude-security`.
