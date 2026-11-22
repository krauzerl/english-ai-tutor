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

## F3 – Treść EN v1: schemat, katalog, pilotaż (2–3 dni) — zależy od F0
Specyfikacja: 04_PEDAGOGY_SPEC §5; instrukcja: `F3_F4_SONNET_BRIEF.md`.
- `tutor/pedagogy/content.py` (schematy pydantic + walidator), `python main.py content validate|review`.
- `content/en/skills/*.yaml` (≥80 umiejętności, 5 domen), `errors.yaml`, `variants.yaml`, `stt_confusables.yaml`, `disfluency.yaml`, `rubric.yaml`, `reviewers.yaml` (pusty szablon), 5 scenariuszy (w tym rekrutacja IT), prompty `turn_eval`, `rubric_eval`, `report_narrative`, `gen_item`, `solve_item`.
- Bank pilotażowy 60 zadań (3 × 4 obszary × A1–C1) + `tools/gen_items.py` (zapis tylko `draft`). **Nie** generować pełnego banku.
- DoD: T-CONTENT-1/3/4/5 zielone; statusy zgodne z rzeczywistością (nic nie `human_reviewed` bez człowieka). T-CONTENT-2 = brama włączenia diagnozy, wymaga recenzenta (poza F3).

## F4 – Pedagogy core (4–5 dni) — zależy od F1, F3
Specyfikacja: 04_PEDAGOGY_SPEC §2–§4, §6–§8.
- Migracja `003_pedagogy.sql` (tylko ADD COLUMN + nowe tabele) i metody repo.
- `cefr.py`, `diagnosis.py` (siatka bayesowska), `schemas.py`, `assessment.py`, `fluency.py`, `correction.py`, `mastery.py`, `srs.py`, `retention.py`, `errors.py`, `planner.py`, `report.py`.
- DoD: kryteria odbioru 04_PEDAGOGY_SPEC §11; T-PED-*, T-RET-*, T-ASSESS-*, T-CORR-1..3, T-ERR-1, T-REPORT-*, T-DB-3, T-LANG-1, T-ARCH zielone.

## F4.5 – Projekt treści otwartych i bramy jakości (wykonane, dokument) — po F4
Specyfikacja: `07_CONTENT_QUALITY_SPEC.md`. Źródła i licencje, biblioteka dydaktyczna, słownictwo NGSL, LanguageTool opcjonalny, benchmark jakości oceny. Bez kodu.

## F4.6 – Treść otwarta, słownictwo, LanguageTool, benchmark (3–4 dni) — zależy od F4.5
Instrukcja: `F4_6_SONNET_BRIEF.md` (checkpointy C1–C6).
- C1 źródła i licencje (`sources.yaml`, `refs`/`license`, ekstraktor poza Git, ATTRIBUTION); C2 słownictwo (`ngsl.csv`, migracja 004, `vocab.py`, `vocab_targets`); C3 pilotaż 12 umiejętności (~84 zadania, pula `retention`); C4 adapter LanguageTool + `lt_merge` (instalacja tylko za zgodą); C5 złoty zbiór 130+11 i `bench/grammar.py` (A/B/C); C6 brama: obserwacje z rozmowy nie obniżają mastery do czasu benchmarku.
- DoD: kryteria odbioru C6 w briefie; T-SRC-*, T-VOC-*, T-LT-*, T-BENCH-*, T-CONTENT-6..8, T-GATE-1 zielone; 0 `human_reviewed`; brama diagnozy zamknięta.

## F5 – Serwisy aplikacji + CLI end-to-end (2 dni) — zależy od F2, F4, F4.6
- `SessionService` (cykl lekcji, kolejka oceny, korekta 3 tryby, checkpointy, raport sesji, next_plan), `DiagnosisService`, `ReviewService`.
- Kolejka oceny z opcjonalnym krokiem LanguageTool (07 §4.2) i `vocab_targets` w rozmowie (07 §3.5).
- `WhisperSTT.transcribe_detailed()` (dodatkowa metoda, bez przebudowy modułu głosowego); pomiar p50/p95 opóźnienia oceny Bielikiem (T-CORR-4).
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
- DoD: raport z liczbami dla ≥3 modeli (Bielik 11B v2.3, ≥1 inny lokalny np. Qwen/Gemma ~8–12B; Gemini gdy przestanie być odroczony).
- Benchmark gramatyki A/B/C (Bielik / LanguageTool / hybryda) przygotowany w F4.6 (07 §5); F8 rozszerza go o inne modele.
- Brama trybów korekty (04_PEDAGOGY_SPEC §3.3): precyzja `error` ≥ 0.80 i fałszywe alarmy < 10% na złotym zbiorze, inaczej domyślnie `summary`. Kalibracja pewności h/m/l.

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
    └─ F3 ─┴─ F4 ─ F4.6 ┘
    F2+F3 ─ F8 (równolegle)
```
Szacunek MVP: ~22–27 dni pracy.
