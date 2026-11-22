# Instrukcja dla Sonnet – F4.6: materiały otwarte, słownictwo, LanguageTool, benchmark jakości

Kontekst: repo `english-ai-tutor`, `main` zawiera F0–F4 (scalone). Projekt: `07_CONTENT_QUALITY_SPEC.md` — źródło prawdy dla F4.6; nad nim `04_PEDAGOGY_SPEC.md` i decyzje w `HANDOFF.md`. **Nie powtarzaj audytu ani projektu.** Sprzeczność zgłoś w raporcie, nie rozstrzygaj po cichu.

Jeden etap, sześć checkpointów (C1–C6). Każdy checkpoint = osobny commit z zielonymi testami. Po C1 i po C4 zatrzymaj się i zapytaj użytkownika, jeśli brakuje plików lub zgody (pobranie, `sudo`).

## Czytaj w tej kolejności
1. `HANDOFF.md`, `07_CONTENT_QUALITY_SPEC.md` (całość), `05_F3_CONTENT_REPORT.md`, `06_F4_PEDAGOGY_REPORT.md`.
2. `04_PEDAGOGY_SPEC.md` §2.3–§2.9, §4.7, §5.
3. Kod: `tutor/pedagogy/content.py`, `assessment.py` (`classify`), `srs.py`, `planner.py`, `tutor/app/ingest.py`, `tutor/store/db.py` + migracje, `tools/gen_items.py`, `tutor/cli.py`, `tests/helpers.py`.

## Zasady pracy
- Gałąź `feat/f4-6-content-quality` z `feat/content-quality-design`. Push po kontroli sekretów; **nie scalaj do `main`**.
- TDD (`superpowers:test-driven-development`), na końcu `superpowers:verification-before-completion`. Ponytail: bez nowych zależności (EPUB/XHTML/XLSX przez stdlib; HTTP przez istniejące `requests`), bez abstrakcji „na później”.
- Tylko `.venv/bin/python|pytest|ruff`. Testy nie wołają modeli ani LanguageTool (fikstury JSON); live tylko `-m live`.
- `tutor/pedagogy/` bez I/O poza `content.py`; T-ARCH-1 obowiązuje dla nowych modułów (`vocab.py`, `lt_merge.py`).
- **Nie zmieniaj** `tutor/voice/`, schematu rdzenia F4 (poza §2.1 i migracją 004 z `ADD COLUMN`), domyślnego modelu (Bielik 11B). Bez Gemini, RAG, agentów, wektorów.
- **Nigdy** `human_reviewed` z AI; adaptacje = `provenance.source: ai_adapted`, `review.status: draft`.
- **Nigdy do Git:** PDF, EPUB, XHTML, ekstrakty (`content_sources/extracted/`), bazy `.db`, nagrania, `.env`. Dopisz wzorce do `.gitignore` (`*.pdf`, `*.epub`, `extracted/`), jeśli brak.
- Do LLM tylko pojedynczy fragment ≤ 1500 tokenów (spec §1.2). Autor adaptacji: Ty (Claude) w sesji lub `tools/gen_items.py` (rola `generation`); zapisz `provenance.model`.
- Dokumenty i komentarze po polsku.

## C1 – Źródła i licencje
1. **Pliki do pobrania (zapytaj użytkownika o zgodę, podaj nazwy, URL i rozmiar):** XHTML (lub EPUB) `esol23`, `greentea`, `technicalwriting` z menu „Download this book” Pressbooks; `NGSL_12_stats.csv`; NGSL-Spoken: `NGSL-Spoken_12_lemmatized_for_teaching.csv`, `NGSL-Spoken_12_stats.csv`, `NGSL-Spoken_12_with_en_definitions.csv` (`https://www.newgeneralservicelist.com/s/<nazwa>`). Zapis do `~/.local/share/english-ai-tutor/content_sources/{textbooks,vocabulary}/`, dopisanie do `REGISTRY.md` i `SHA256SUMS`. Bez zgody: pracuj na PDF (tylko Brehe) i plikach lokalnych, `rank` puste — odnotuj w raporcie.
2. `tutor/content/en/sources.yaml` (spec §1.1, §2.3): id, tytuł, autorzy, URL, licencja, sha256, `exclude`, `map`. `SUP` nieobecny.
3. Schemat (`content.py`): `Provenance.source` += `ai_adapted`; `refs: list[SourceRef]`; `license` (wymagane przy `refs`). Walidator: `refs.src` istnieje w `sources.yaml`; ShareAlike (§1.3); `sha` zgodny z `sources.yaml` (ostrzeżenie przy różnicy); `loc` nie wskazuje na `exclude`.
4. `tools/source_extract.py`: EPUB/XHTML (stdlib) i PDF Brehe (`pdftotext`, normalizacja ligatur) → JSONL w `content_sources/extracted/`. Pomija `exclude`, media osadzone (iframe/H5P), ryciny.
5. Kontrola nakładania: funkcja walidatora wykrywająca ≥ 12 wspólnych kolejnych słów z fragmentem źródła wskazanym w `refs` (działa, gdy ekstrakt jest lokalnie; bez niego pomija z ostrzeżeniem — CI bez źródeł nie pada).
6. `tutor/content/en/ATTRIBUTION.md` generowany z `sources.yaml` (`main.py content attribution en`).
7. Testy: T-SRC-1..4 (TEST_PLAN).
**Odbiór C1:** `content validate en` czyste; `git ls-files | grep -iE '\.(pdf|epub|xhtml)$|extracted/'` puste; ATTRIBUTION zawiera wszystkie 6 źródeł z licencjami.

## C2 – Słownictwo
1. `tools/import_ngsl.py` → `tutor/content/en/vocab/ngsl.csv` wg spec §3.1 (kolumny, `variants`, `homograph`, `rank`/`freq_band` tylko ze stats, `spoken`, `cefr` puste, `gloss_pl` puste, nagłówek z atrybucją CC BY-SA 4.0 i SHA wejść). XLSX przez `zipfile` + `xml.etree`.
2. `content.py`: ładowanie `ngsl.csv` (lazy; < 50 ms), walidacja (2809 unikalnych lematów; `rank` unikalny; brak `cefr`).
3. Migracja `004_vocab.sql`: tylko `ALTER TABLE vocab ADD COLUMN` (spec §3.2); backup jak w 003. Repo: metody z `profile_id`.
4. `tutor/pedagogy/vocab.py`: przejścia `unknown/passive/active`, wynik testu tak/nie z korektą h−f, polityka tworzenia kart (spec §3.4, limity z `rubric.yaml`), detekcja użycia w wypowiedzi (formy + warianty, bez echa tutora, bez `disfluency`, bez prob < 0,5).
5. `planner.py`: `vocab_targets` (≤ 5) w planie — jedyna zmiana planera.
6. `ingest.py`: użycie słowa w rozmowie → `used_count`, karta Good (jeśli zaległa).
7. `vocab/pseudowords.yaml` (~30 pseudosłów, `draft`) — test rozpoznawania oznacza wynik „wstępny”, dopóki pseudosłowa nie są `human_reviewed`.
8. Testy: T-VOC-1..7.
**Odbiór C2:** nowy profil ma 0 kart `vocab` po imporcie; test, że kolejność wierszy nie wpływa na `rank`; `colour`/`color` uznane w detekcji; T-ISO i T-DB-3/4 zielone.

## C3 – Pilotaż treści (12 umiejętności)
1. Umiejętności i wymagania: spec §2.5 (tabela i lista „na każdą umiejętność”). Mapa `sources.yaml map:` ręcznie dla tych 12.
2. Wyjaśnienia `grammar/*.md` w strukturze §2.2 (rozbuduj istniejące, dodaj brakujące); walidator struktury `.md`.
3. Zadania: 4 `practice` + 3 `retention` na umiejętność (≈ 84), pliki `items/<area>/<cefr>.yaml`, id `en.f46.<area>.<cefr>.<nn>`. Pule `retention` i `practice` rozłączne. Nie dodawaj do puli `diagnosis`.
4. `phrases.yaml` (≥ 6 zwrotów dla umiejętności 4, 7–9, 11), `errors.yaml`: nowe podkategorie `l1_calque.*` używane przez pilotaż.
5. `content review` obsługuje też wyjaśnienia, scenariusze, zwroty i przypadki benchmarku (status w front matter / polu `review`).
6. Kontrola na ślepo (`tools/gen_items.py --solve-check`, Bielik, lokalnie, koszt 0) dla nowych zadań — notatka „sędzia niezwalidowany” (spec §8 pkt 5).
7. Testy: T-CONTENT-6..8.
**Odbiór C3:** `content validate en` liczy 12 umiejętności z kompletem; 0 `human_reviewed`; `retention_gaps` nie zwraca 12 pilotażowych; brama `diagnosis_gate()` nadal `open=False`.

## C4 – LanguageTool (adapter, bez instalacji przez Ciebie)
1. `tutor/app/languagetool.py`: `check()` wg spec §4.2 (localhost-only, `enabled=false` domyślnie, timeout 1,5 s, `None` przy błędzie). `config.toml [languagetool]`.
2. `tutor/content/en/lt_map.yaml` (spec §4.3–§4.4); walidator: kategorie istnieją w `errors.yaml`.
3. `tutor/pedagogy/lt_merge.py`: konwersja dopasowań → kandydaci, reguły R1–R7, filtr pisowni BrE/AmE (NGSL `forms` + `variants.yaml` + reguły), wynik przez istniejące `classify()`.
4. Kolejka oceny jeszcze nie istnieje (F5) — dodaj tylko punkt wywołania w funkcji oceny używanej przez benchmark; nie podłączaj do rozmowy.
5. **Instalacja LT (punkt zatrzymania):** zapytaj użytkownika. Wymaga `sudo apt install openjdk-17-jre-headless` i pobrania `LanguageTool-*.zip` (podaj wersję, URL, rozmiar). Po zgodzie użytkownik uruchamia serwer (`java -Xmx512m -cp languagetool-server.jar org.languagetool.server.HTTPServer --port 8081 --config server.properties`, bez `--public`, bez `--allow-origin`) — instrukcję wpisz do raportu. Potem: zapisz prawdziwą odpowiedź `/v2/check` jako fiksturę kontraktu, potwierdź nazwy parametrów, reguł i kluczy konfiguracji z spec §4.1, uzupełnij `lt_version_tested`. Bez zgody: C4 kończy się na testach z fiksturami pisanymi ręcznie, oznaczonymi „kontrakt niezweryfikowany”.
6. Testy: T-LT-1..6.
**Odbiór C4:** aplikacja i wszystkie testy działają przy wyłączonym/nieosiągalnym LT; URL spoza localhost odrzucony; `curl` na port z innego hosta nie dotyczy (serwer bez `--public`).

## C5 – Benchmark jakości
1. `bench/cases/en/grammar_gold.yaml`: 130 przypadków wg spec §5.1 (podzbiory i liczności dokładnie), `review.status: draft`. Pisz zdania sam; **nie** kopiuj z podręczników ani banku. Przypadki głosowe z `words` (prob) i par z `stt_confusables.yaml`.
2. `bench/cases/en/f3_mismatch.yaml`: 11 zadań F3 (id z spec §5.1) z polem na klucz człowieka.
3. `bench/grammar.py` (CLI: `python -m bench.grammar --system A|B|C [--only-reviewed]`): miary spec §5.3, przedziały Wilsona, per podzbiór i per kategoria, pomiar opóźnień i zasobów (`/proc`, `nvidia-smi` jeśli jest). Wynik JSON + Markdown.
4. Testy harnessu na FakeProvider i fiksturach LT (T-BENCH-1..4). Uruchomienie live (`-m live` / ręczne) **tylko** po C4 z działającym LT i Ollamą; bez recenzji złotego standardu raport oznacz „WSTĘPNY – złoty standard niezrecenzowany, bramy nieotwierane”.
**Odbiór C5:** harness działa offline na fiksturach; przy danych live raport `docs/ai-work/BENCHMARK_GRAMMAR.md` z liczbami dla A, B, C albo jawny powód braku (np. LT niezainstalowany).

## C6 – Brama jakości i raport
1. `rubric.yaml correction.quality_gate`: `trusted_categories: []`, `lt_trusted_rules: []`, `judge_agreement_min: 0.90`, `category_precision_min: 0.85`, `category_min_n: 8`.
2. `ingest.py`: obserwacje z rozmowy spoza `trusted_categories` nie obniżają BKT i nie zmieniają statusów mastery; `error_log` działa jak dotąd (spec §5.5). Testy aktualizowane jawnie (to zmiana decyzji, opisz w raporcie).
3. Nie zmieniaj `bielik_benchmark_passed`, `trusted_categories` ani statusów treści na podstawie benchmarku bez recenzji człowieka — wyniki tylko w raporcie z rekomendacją.
4. Raport `docs/ai-work/08_F4_6_REPORT.md`: co zrobione per checkpoint, liczności, wyniki (lub ich brak), odstępstwa, ryzyka, decyzje dla użytkownika. Aktualizacja `HANDOFF.md` (status).
**Odbiór C6 (= odbiór F4.6):**
1. `.venv/bin/pytest` zielone (≥ 246 dotychczasowych + nowe), `ruff check .` czyste; `tests/test_voice_*` bez zmian i zielone.
2. `python main.py content validate en` czyste; liczności w raporcie; 0 `human_reviewed`.
3. T-SRC-*, T-VOC-*, T-LT-*, T-BENCH-*, T-CONTENT-6..8, T-GATE-1 zielone; T-ARCH-1/2, T-LANG-1, T-ISO-* zielone.
4. Brak plików źródłowych, ekstraktów, baz i sekretów w diffie.
5. `diagnosis_gate()` = `open=False`; tryb domyślny `summary`.

## Czego nie robić
F5 (kolejka oceny, `transcribe_detailed()`, integracja z rozmową), GUI, pełny bank 300 zadań, karty dla wszystkich słów NGSL, CEFR słów z częstości, zmiany w `tutor/voice/`, Gemini, scalanie do `main`, `human_reviewed` z AI, instalacja czegokolwiek z `sudo` bez zgody, użycie `SUP_lemmatized.csv`, publiczne API LanguageTool.

## Przed push
`git diff feat/content-quality-design... | grep -inE 'api[_-]?key|secret|token|password|@[a-z0-9-]+\.[a-z]'` i `git diff --stat ... | grep -iE '\.(pdf|epub|db|wav)'` — przejrzyj trafienia; żadnych ścieżek domowych z danymi ucznia.
