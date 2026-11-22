# IMPLEMENTATION PLAN

Każda faza = osobna gałąź i PR, TDD (Superpowers `test-driven-development`), na końcu `verification-before-completion`. „DoD” = kryterium ukończenia.

## F0 – Przygotowanie środowiska (0.5 dnia)
- Zaktualizować Ollamę (0.9.0 → aktualna), `sudo systemctl enable --now ollama` (decyzja użytkownika).
- `pyproject.toml`, pakiet `tutor/`, `pytest`, `ruff`. `main.py --cli` = obecne zachowanie.
- DoD: `pytest` przechodzi (1 test smoke), `python main.py --cli` rozmawia jak dziś.

## F1 – Store + profile (1–2 dni) — zależy od F0
- `store/db.py`, migracja 001 (ARCHITECTURE §3), `repo.py`, eksport JSON, usunięcie kaskadowe.
- DoD: T-ISO-* i T-DB-* zielone; eksport/usunięcie działa z CLI.

## F2 – Warstwa LLM (2 dni) — zależy od F0
- `llm/base.py`, `ollama.py` (przeniesienie z `main.py`), `structured.py`, `meter.py`, `context.py`, `gemini.py`.
- Obsługa błędów: timeout, brak serwera, zły JSON, limit.
- DoD: T-LLM-* zielone na fake providerze; ręczny test z Ollamą i Gemini; limity blokują wywołanie.

## F3 – Treść EN v1 (2–3 dni, równolegle z F2) — zależy od F0
- `content/en/skills.yaml` (~60 umiejętności A1–C1), `items/` (≥ 15 zadań zamkniętych na poziom × obszar grammar/vocab/reading/listening = ~300), 5 scenariuszy (w tym rekrutacja IT), prompty, `errors.yaml`.
- Generowanie wspomagane LLM dozwolone, ale każde zadanie przegląda człowiek (flaga `reviewed: true`). Walidator schematu treści.
- DoD: T-CONTENT-* zielone; 100% zadań `reviewed`.

## F4 – Pedagogy core (3 dni) — zależy od F1, F3
- `cefr.py`, `diagnosis.py`, `mastery.py`, `srs.py`, `errors.py`, `planner.py`, `rubric.py`.
- DoD: T-PED-* zielone (symulowani uczniowie); brak importów `llm/` (T-ARCH).

## F5 – Serwisy aplikacji + CLI end-to-end (2 dni) — zależy od F2, F4
- `SessionService` (cykl lekcji, korekta 2 tryby, checkpointy, podsumowanie, next_plan), `DiagnosisService`, `ReviewService`.
- DoD: pełna sesja 15 min w CLI na Ollamie: diagnoza → lekcja → rozmowa → podsumowanie zapisane; T-INT-* zielone.

## F6 – GUI PySide6 (4–5 dni) — zależy od F5
- Kolejność widoków: Wybór profilu → Dashboard → Dzisiejsza lekcja → Konwersacja (tekst) → Słownictwo/powtórki → Gramatyka → Historia → Profil kompetencji → Ustawienia (modele, limity, zgoda, eksport/usuń).
- Workery w `QThreadPool`, anulowanie.
- DoD: T-UI-* zielone (pytest-qt); ręczny przegląd wg ARCHITECTURE §8.

## F7 – Mowa (2–3 dni) — zależy od F5 (GUI integracja po F6)
- `audio.py`, `stt.py`, `tts.py`, push-to-talk, listening w diagnozie, metryki płynności.
- DoD: T-SPEECH-* zielone; pomiar RAM/VRAM z Bielikiem 11B na GPU + Whisper CPU bez OOM; opóźnienie tury głosowej zmierzone i zapisane.

## F8 – Benchmark modeli (2 dni) — zależy od F2, F3 (może iść równolegle z F4–F7)
- `bench/` wg TEST_PLAN §6; raport `docs/ai-work/BENCHMARK.md`; wybór modeli domyślnych per rola.
- DoD: raport z liczbami dla ≥3 modeli (Bielik 11B v2.3, ≥1 inny lokalny np. Qwen/Gemma ~8–12B, ≥1 Gemini).

## F9 – Utwardzenie MVP (2 dni) — zależy od wszystkich
- `/security-review`, `claude-security`, testy regresji, backup DB przed migracją, README.
- DoD: wszystkie testy zielone; brak krytycznych znalezisk; checklista RQ-8.* spełniona.

## Po MVP
- P2: włoski (`content/it`), IRT 1PL, podsumowania miesięczne, PDF raportów, więcej scenariuszy, PIN profilu.
- P3: ocena wymowy (model fonemowy + GOP), adaptacyjne tempo TTS, import słownictwa.

## Graf zależności
```
F0 ─┬─ F1 ─┐
    ├─ F2 ─┼─ F5 ─ F6 ─ F7 ─ F9
    └─ F3 ─┴─ F4 ┘
    F2+F3 ─ F8 (równolegle)
```
Szacunek MVP: ~22–27 dni pracy.
