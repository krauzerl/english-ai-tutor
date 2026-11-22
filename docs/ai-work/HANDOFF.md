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

## Pierwsze kroki (F0 → F1)
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
