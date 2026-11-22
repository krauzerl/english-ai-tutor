# Raport F4.6 — materiały otwarte, słownictwo, LanguageTool, benchmark jakości

Gałąź `feat/f4-6-content-quality` (z `feat/content-quality-design`, `710e26e`). Nie scalono do `main`. F5 nie rozpoczęto.
Testy: **307 zielonych**, 1 pominięty, 11 `live` odfiltrowanych (było 248). `ruff` czysty. `content validate en`: OK.

## Wynik w skrócie
- Wszystkie checkpointy C1–C6 wykonane, każdy jako osobny commit.
- **Benchmark Bielika NIE przeszedł** (precision 0,771, FPR 0,240, poprawność korekty 0,531, p95 kolejki 20,7 s). Zgodnie z decyzją: bezpieczny tryb sugestii zostaje, to nie blokada rozwoju.
- **Żadna brama nie została odblokowana**: `diagnosis_gate` zamknięta, `bielik_benchmark_passed: false`, `trusted_categories: []`, `lt_trusted_rules: []`. 0 elementów `human_reviewed`.
- Wyniki benchmarku są **WSTĘPNE** (złoty standard pisany przez AI, niezrecenzowany).

## C1 — źródła i licencje
- Pobrano (oficjalne linki, zgoda użytkownika): `esol23.xhtml`, `greentea.xhtml` (Pressbooks, wymagany nagłówek User-Agent przeglądarki), `NGSL_12_stats.csv`, `NGSL-Spoken_12_{lemmatized_for_teaching,stats,with_en_definitions}.csv`. Wpisy w `REGISTRY.md` i `SHA256SUMS`; katalogi biblioteki były tylko do odczytu — odblokowane na czas dopisania i przywrócone.
- **Technical Writing Essentials**: strona BCcampus za wyzwaniem Cloudflare. Nie omijano ochrony antybotowej; import z lokalnego PDF. Oficjalny PDF Brehe nie był potrzebny (lokalny kompletny; ligatury normalizowane).
- `sources.yaml` (6 źródeł, bez SUP), schemat: `Provenance.source=ai_adapted`, `refs`, `license`; walidator: istnienie źródła, wykluczenia, ShareAlike, zmiana SHA (ostrzeżenie), kontrola nakładania ≥ 12 słów (z lokalnym ekstraktem; bez niego ostrzeżenie, CI nie pada), `ATTRIBUTION.md` (`main.py content attribution en`). `tools/source_extract.py` (stdlib/pdftotext).
- `git ls-files` bez PDF/EPUB/XHTML/ekstraktów; `.gitignore` uzupełniony.

## C2 — słownictwo
- `tools/import_ngsl.py` → `vocab/ngsl.csv`: 2809 lematów, rangi **tylko** z `stats` (test: tasowanie wejścia nie zmienia rang), `cefr` zawsze puste, 10 homografów, 40 lematów z wariantami BrE/AmE, flaga `spoken` (697). Jedna luka źródła: brak definicji dla `email`.
- Migracja `004_vocab.sql` (tylko `ADD COLUMN`; dodatkowo `last_recall_day`, `last_use_session`, `use_sessions`, `card_day` — potrzebne do reguły „różne dni/sesje”).
- `pedagogy/vocab.py`: przejścia unknown/passive/active, test tak/nie z korektą h−f (fałszywe „tak” ≥ 30% ⇒ odrzucony; pseudosłowa niezrecenzowane ⇒ „wstępny”), polityka kart (4 wyzwalacze, limity 10/dzień i 300), detekcja użycia (formy + BrE/AmE, bez echa tutora, wypełniaczy, słów o prob < 0,5). `vocab_targets` ≤ 5 w planie. 30 pseudosłów `draft`. Nowy profil: 0 kart `vocab`.
- **Dodatkowe kryterium:** samo wykrycie słowa w rozmowie **nie** potwierdza opanowania — przy zamkniętej bramie `used_ok` zlicza tylko liczniki, `knowledge` i karty bez zmian.

## C3 — pilotaż treści
- 12 umiejętności: **84 zadania** (4 `practice` + 3 `retention` każda; pule rozłączne; poza `diagnosis`), 12 wyjaśnień wg struktury 07 §2.2 (walidator `.md`), 35 zwrotów w `phrases.yaml`, 3 kategorie `l1_calque.*`. Typy zadań: gap 33, mc 24, transform 12, translate_pl 8, reorder 7.
- Kontrola na ślepo (Bielik, lokalnie, koszt 0): 55 `ai_checked`, 29 `draft` — z notatką „sędzia niezwalidowany”. Większość niezgodności to prawdopodobnie słabość sędziego (potwierdza go benchmark: 0/11), nie błędy kluczy; wymaga recenzji człowieka.
- Źródła: zadania są **własne** (`ai_generated`, bez `refs`); `refs` mają tylko wyjaśnienia. Mapa z 07 §2.3 skorygowana: Green Tea (wykłady/prezentacje) nie zawiera funkcji „prośba o wyjaśnienie/zgoda”, więc `ask_clarification`, `agree_disagree` i kolokacje są bez odwołań.
- `content review` obsługuje też wyjaśnienia, scenariusze, zwroty (`--kind docs`) i przypadki benchmarku (`--kind bench`); tylko ścieżka człowieka nadaje `human_reviewed`.
- **Odstępstwo od odbioru C3:** „`retention_gaps` nie zwraca 12 pilotażowych” — celowo niespełnione. Zgodnie z dodatkowym kryterium rozróżniono pulę **istniejącą** od **dopuszczonej** (`retention_pool_status`): pilotaż ma 3 istniejące zadania `retention` (≥ 1 produkcyjne), ale 0 dopuszczonych (`human_reviewed`); `retention_gaps` nadal je wymienia, test trwałości się odracza.
- Skill `passive_basic` ma poziom B1 (spec: B2) — zadania oznaczono B1.

## C4 — LanguageTool
- **Wersja i Java:** LanguageTool **6.6** (ostatnie wydanie stabilne, 2025-03-27) wymaga **Javy 17+** (CHANGES.md). Systemowej Javy brak. Uruchomiono na JetBrains Runtime 25 z PyCharma (bez `sudo`), `-Xmx512m`, `nice 10`, port 8081, bez `--public` i `--allow-origin` (nasłuch tylko 127.0.0.1). Wariant „oficjalny”, gdy wolisz systemową Javę:
  ```bash
  sudo apt install openjdk-17-jre-headless
  ```
  Paczka: `~/.local/share/english-ai-tutor/tools/languagetool/LanguageTool-6.6.zip` (252 MB, SHA-256 `53600506b399bb5ffe1e4c8dec794fd378212f14aaf38ccef9b6f89314d11631`), rozpakowana obok. Serwer nie jest uruchomiony na stałe. Start ręczny:
  ```bash
  cd ~/.local/share/english-ai-tutor/tools/languagetool/LanguageTool-6.6 && nice -n 10 java -Xmx512m -cp languagetool-server.jar org.languagetool.server.HTTPServer --port 8081 --config server.properties
  ```
- Adapter `tutor/app/languagetool.py`: `enabled=false` domyślnie; host ∈ {127.0.0.1, localhost, ::1} (także przy wyłączonym LT), bez danych logowania w URL; **`allow_redirects=False`** (test na lokalnym serwerze zwracającym 302: jedno żądanie, zero śledzenia) i `trust_env=False`; timeout 1,5 s; błąd/3xx/non-200 ⇒ `None`. Brak dopasowań `[]` ≠ „poprawne”.
- Kontrakt potwierdzony na żywym serwerze (parametry, `rule.id/issueType/category.id`, zapis odpowiedzi w `tests/fixtures/lt/check_real_6_6.json`). Ustalenia: `language=en` (bez odmiany) wyłącza pisownię; `I_AM_VB`, `MORFOLOGIK_RULE_EN_US` dopisane do `lt_map`; `NON3PRS_VERB`, `DT_DT` niepotwierdzone. Kalka „I have 25 years” **nie** jest wykrywana.
- `lt_merge` R1–R7 (czysta funkcja), filtr BrE/AmE, `merge_eval`; punkt wywołania `tutor/app/turn_eval.py` (bez podpięcia do rozmowy — to F5). Formy potoczne (`gonna`, `wanna`, `gotta`, `kinda`) jako warianty, bez wpływu na klucze zadań (`skip_domains`).

## C5 — benchmark (WSTĘPNY)
`python -m bench.grammar --system all --judge`; 130 przypadków (E1 45, E2 15, C1 25, C2 15, C3 10, S 12, D 8) + 11 niezgodności F3; dopasowanie **jednoznaczne 1:1** (maksymalne skojarzenie, bez wielokrotnego liczenia), przedziały Wilsona, minimalna czułość w bramie (`recall_min 0,50`, Wilson ≥ 0,40, `min_reports 10`). Pełny raport: `BENCHMARK_GRAMMAR.md`/`.json`.

| miara | A (Bielik) | B (LT) | C (A+B) |
|---|---|---|---|
| precision | 0,771 [0,67; 0,85] | 0,952 [0,77; 0,99] | 0,771 |
| recall | 0,865 [0,77; 0,93] | **0,263** | 0,865 |
| FPR C1+C2+C3 | **0,240** | 0,000 | 0,240 |
| akceptacja BrE/AmE | 0,733 | 1,000 | 0,733 |
| S / D bez zgłoszeń | 1,0 / 1,0 | 1,0 / 1,0 | 1,0 / 1,0 |
| poprawność korekty | **0,531** | 0,900 | 0,531 |
| zgodność kategorii | 0,516 | 0,300 | 0,516 |
| p95 kolejki | **20,7 s** | 0,04 s | 20,7 s |

- **Żaden system nie jest dopuszczony** (blokery: 0 zrecenzowanych przypadków; A i C nie spełniają też precision/FPR/korekty/opóźnienia; B ma recall 0,26 < 0,50). Rekomendacja per kategoria: tylko `preposition` (A, C; n = 8, p = 1,00) przekracza próg — **niewpisana** do `rubric.yaml`.
- C ≡ A: **zweryfikowane osobno (nie błąd benchmarku ani integracji).** Powtórzono A i C na 45 przypadkach, w których LT coś zgłosił (23 z użytecznym kandydatem): 0 różnic. Przyczyny: (1) Bielik zwraca span = całe zdanie, a LT span minimalny („do”, „have”), więc nakładają się, ale nie są tym samym spanem ⇒ zgodnie z regułą **R2** zostaje obserwacja Bielika, a alternatywa LT trafia do logu; **R1** (ten sam span ⇒ podniesienie pewności) w praktyce nie zachodzi; (2) kandydaci tylko-LT mają `p=l` i są sugestiami — test na Bieliku zwracającym `o=[]` pokazał je w C jako sugestie (`g.e1.043`, `g.e2.013`, `g.e1.036`), czyli integracja działa; w pełnym przebiegu tych przypadków Bielik był nieoceniony (4 odpowiedzi strukturalne niepoprawne ⇒ `unrated`, LT sam niczego nie ocenia) albo spany się nakładały; (3) w głosie LT w słowach o niskim prob daje `stt_suspect`. Wniosek: reguły działają zgodnie ze specyfikacją; słabość to szeroki span Bielika (zawyża też dopasowanie 1:1). Do rozważenia w F8: R1 z kryterium zawierania spanu oraz wymuszenie minimalnego spanu w prompcie `turn_eval`. LT jest bardzo precyzyjny, ale ma niską czułość.
- Bielik słabo rozróżnia tense (22/33) i omission (11/14), myli się w BrE/AmE (FPR C2 0,27). Sędzia zadań: **0/11** zgodności z kluczem w bazie ⇒ `--solve-check` pozostaje notatką „sędzia niezwalidowany”, a próg 0,90 nie jest spełniony.
- Zasoby: LT RSS 664 MiB (≤ 1 GiB OK), CPU LT ≈ 1,3%, VRAM 6,97 GiB, p95 LT 35 ms (≤ 300 ms OK). **TTFT rozmowy po sprawdzeniu LT pogorszone 0,17 → 0,60 s (+254%, kryterium ≤ 5% niespełnione)**; pomiar z n = 3 i Bielikiem częściowo na CPU — wymaga powtórzenia, ale LT na pewno nie powinien działać równolegle ze strumieniem rozmowy.
- Ograniczenia: złoty standard niezrecenzowany; zdania pisane przez Claude (możliwy bias stylu); wyniki jednego uruchomienia na jednym sprzęcie.

## C6 — brama jakości (zmiana zachowania względem F4)
- `rubric.yaml correction.quality_gate`: `trusted_categories: []`, `lt_trusted_rules: []`, `judge_agreement_min 0,90`, `category_precision_min 0,85`, `category_min_n 8`, `recall_min`, `recall_wilson_low_min`, `min_reports`.
- `ingest.apply_turn_evaluation`: obserwacje z rozmowy spoza `trusted_categories` zostają w `observation`/`error_log`, ale **nie tworzą prób, nie zmieniają BKT ani statusów mastery**. Twierdzenia modelu o użyciu konstrukcji celu (`t`) zmieniają mastery tylko po potwierdzeniu deterministycznym (`target_patterns`). Wynik wypowiedzi zawiera `events.gated`. Brak wykrytego błędu nie tworzy żadnego dowodu.
- **Rozstrzygnięcie (ruling):** spec 07 §5.5 zachowywał zadania naprawcze z `error_log`; dodatkowe kryterium użytkownika jest ostrzejsze („nie wymuszać lekcji naprawczych”). Planer dla niezaufanych kategorii nie dodaje zadań `remediation`, tylko wpisy `plan["suggested"]` z `unverified: true`. Koszt: uczeń nie dostanie automatycznych lekcji naprawczych z rozmowy do czasu otwarcia bramy.
- Testy F4 zaktualizowane jawnie (fixture `open_gate`: mechanika F4 przy zaufanych kategoriach); domyślne zachowanie bramy: `tests/test_gate.py`.

## Odstępstwa i rozstrzygnięcia
1. `retention_gaps` nadal wymienia pilotaż (pula istniejąca ≠ dopuszczona) — patrz C3.
2. Zadania pilotażu bez `refs` (własne), wyjaśnienia z `refs`; mapa źródeł skorygowana (Green Tea).
3. TWE bez pobrania XHTML (Cloudflare); Brehe bez oficjalnego PDF.
4. LT uruchomiony na Javie 25 z PyCharma (poza oficjalnym wymogiem 17+, działa; wersja 17 zalecana przy instalacji systemowej).
5. Strażnik `used_ok` w słownictwie (kryterium użytkownika) zmienia opis ścieżki „active” z 07 §3.2: aktywne przez rozmowę dopiero po otwarciu bramy.
6. Testy: 4 istniejące zaktualizowano (liczności F3 vs pilotaż, deferral retention dla innej umiejętności, mechanika F4 przy zaufanych kategoriach).
7. `pyproject.toml`: dodano `**/*.csv` do `package-data` (inaczej `ngsl.csv` nie trafiłby do paczki).

## Ryzyka
- Nowe 84 zadania i 35 zwrotów to treść AI bez recenzji; `ai_checked` pochodzi z niezwalidowanego sędziego.
- LT obciąża CPU przy Bieliku z offloadem (TTFT); używać tylko w kolejce oceny.
- Kryteria bramy wymagają ocen człowieka (znaczenie, wyjaśnienia) — brak ich = brama nie otworzy się nawet po recenzji spanów.
- Licencja Brehe tylko wg noty w PDF; piper-tts (GPL-3.0) jako opcjonalna zależność.

## Decyzje dla użytkownika
1. **Licencje** — potwierdź propozycję z `LICENSING_PROPOSAL.md` (MIT kod; CC BY-SA 4.0 treści i `bench/cases`; właściciel praw i rok; co z piper-tts). Do tego czasu nie dodano żadnego `LICENSE`.
2. Recenzent: złoty standard (130 przypadków + 11 F3, `content review en --reviewer <id> --kind bench`), pilotaż (`--kind items|docs`) i `reviewers.yaml` (obecnie pusty).
3. Java: zostać przy JBR z PyCharma czy zainstalować `openjdk-17-jre-headless` (polecenie wyżej)?
4. Czy LT ma wejść do F5 jako opcjonalny walidator o wysokiej precyzji (tylko kolejka, nie równolegle ze strumieniem), mimo recall 0,26?
5. Czy kategorię `preposition` rozważać do `trusted_categories` dopiero po recenzji i powtórzeniu pomiaru na większej próbie (n = 8)?
