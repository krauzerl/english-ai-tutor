# HANDOFF – start implementacji

Audyt zakończony 2026-11-22. Nie powtarzaj go. Czytaj w kolejności: ten plik → REQUIREMENTS → ARCHITECTURE → IMPLEMENTATION_PLAN → TEST_PLAN. AUDIT tylko w razie wątpliwości.

## Stan wyjściowy
- Repo: `main.py` (40 linii, CLI chat z Ollamą), puste `ollama_client.py`, `prompts.py`. Brak testów. Branch `main`, czysty.
- Zachować: wywołanie `/api/chat` z `main.py` → przenieść do `tutor/llm/ollama.py`; `main.py --cli` zachowuje obecne zachowanie. Puste pliki usunąć w F0.
- `.venv` = Python 3.12.3, zawiera tylko `requests`. Instalować zależności do `.venv`, nie do systemowego 3.13 ani anacondy.

## Środowisko — fakty
- Ubuntu 24.04, Ryzen 7 3700X, 31 GiB RAM, RTX 2060 SUPER **8 GiB VRAM**.
- Ollama 0.9.0, serwis **wyłączony** — uruchom `ollama serve` lub poproś użytkownika o `sudo systemctl enable --now ollama`. Modele: `SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M`, `bielik-7b-instruct-v0.1-gguf`.
- Brak: faster-whisper, piper, PySide6, ffmpeg (ffmpeg niepotrzebny). `GEMINI_API_KEY` nieustawiony — użytkownik ma dostęp na rok; poprosić o klucz do `~/.config/english-ai-tutor/.env`, nigdy do repo.
- Whisper uruchamiać na CPU (int8) gdy Bielik 11B na GPU — razem nie mieszczą się w 8 GiB.

## Kluczowe decyzje (nie zmieniać bez powodu)
1. Silnik dydaktyczny `tutor/pedagogy/` czysty, deterministyczny, bez LLM.
2. SQLite + `sqlite3` bez ORM; każda tabela ucznia ma `profile_id` z `ON DELETE CASCADE`.
3. Bez RAG, wektorów, agentów, serwera HTTP.
4. LLM tylko przez `LLMProvider`; odpowiedzi strukturalne walidowane pydantic, 1 retry.
5. Diagnoza: staircase per obszar, niezależne obszary, wynik z przedziałem niepewności.
6. SRS: biblioteka `fsrs`. Mastery: BKT ze stałymi parametrami.
7. Wymowa poza MVP; nigdy nie twierdzić, że poprawna transkrypcja = poprawna wymowa.
8. Treść językowa wyłącznie w `content/<lang>/`; zadania przeglądane przez człowieka (`reviewed: true`).
9. Zewnętrzne API wymaga zgody per profil; limity kosztów w `config.toml` (cennik wpisuje użytkownik/weryfikuje z Google).

## Status
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
- Kto przegląda bank zadań F3 (wymagane człowiek, ~300 zadań)?
- Odmiana domyślna: BrE czy AmE (obie akceptowane w ocenie; dotyczy głosu TTS i generowanych przykładów).
- Czy zapisywać nagrania audio (domyślnie nie)?

## Narzędzia
Ponytail (minimalizm), Superpowers (plany, TDD, weryfikacja), Caveman (czat). Impeccable niedostępny — zasady UI w ARCHITECTURE §8. Bezpieczeństwo: `/security-review`, agent `claude-security`.
