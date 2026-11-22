# F4 – rdzeń dydaktyczny (raport)

Gałąź `feat/f4-pedagogy` (z `feat/f3-content`). Źródło prawdy: `04_PEDAGOGY_SPEC.md` + decyzje nadrzędne użytkownika. Nic nie scalono do `main`; F5 nie rozpoczęte.

## Co zrobione
- **Migracja `003_pedagogy.sql`** (tylko `ADD COLUMN` + nowe tabele `observation`, `turn_meta`); `Repo`: transakcje, `observation`, `turn_meta`, próby z `dedupe_key`, stany umiejętności, `error_log` (stan pochodny), SRS, kompetencje, `diagnosis_run`, plan.
- **`tutor/pedagogy/`**: `cefr`, `diagnosis`, `mastery`, `srs`, `retention`, `errors`, `schemas`, `assessment`, `fluency`, `correction`, `planner`, `report` (+ `content` z F3). Parametry liczbowe z `rubric.yaml`.
- **`tutor/app/ingest.py`** (nowy, cienki): jedyne miejsce zapisu postępów z wyniku oceny: `apply_turn_evaluation`, `apply_item_attempt`, `apply_retention_result`. To nie jest integracja z rozmową/kolejką (F5).
- Testy: `test_ped_core`, `test_assessment`, `test_f4_flow`, `test_pedagogy_db`, rozszerzone `test_isolation`; syntetyczny pakiet `tests/fixtures/content/xx/`.

## Wyniki testów
`.venv/bin/pytest`: **246 passed, 1 skipped, 11 deselected (live)**; `.venv/bin/ruff check .`: czysto. Baza przed F3/F4: 132 testy.

Symulacje diagnozy (500 uczniów, ten sam model w symulacji i estymatorze, ziarno stałe; **to nie jest walidacja CEFR – spec §4.4**): poziom w ±1 od „prawdy”: 94,2% (próg 90%); przedział 80% (w etykietach poziomów) zawiera prawdziwy poziom: 93,8% (próg 90%); średnio 10,0 zadań (limit); przedział maleje z liczbą zadań (test). Czas przetwarzania jednej tury (prefiltr + klasyfikacja): ≈0,15 ms (cel < 5 ms); planer przy 500 umiejętnościach, 1500 zadaniach i 300 kartach < 50 ms (test).

## Decyzje użytkownika – jak wdrożone
1. **Wstępne dopasowanie z banku `ai_checked`.** `diagnosis` ma tryby `verified` (tylko `human_reviewed`, brama ≥15/poziom) i `provisional` (`ai_checked` lub `human_reviewed`, ≥5 zadań). Wynik provisional: `Result.provisional=True`, etykieta „wstępnie: …”, `competence.source=placement_provisional`, obowiązkowy tekst „… nie jest diagnozą CEFR”; raport i planer też to oznaczają (`provisional_level`). Testy trwałości i `cefr_check` zawsze tylko `human_reviewed`. Na prawdziwym pakiecie: `verified` → `GateClosed` (0 zrecenzowanych), `provisional` działa w 4 obszarach.
2. **Domyślny tryb `summary`**: kolumna `profile.correction_style DEFAULT 'summary'`; `Repo.create_profile`; `rubric.correction.default_style` + `quality_gate.bielik_benchmark_passed: false`. Wybór `periodic`/`intensive` jest respektowany, ale `effective_style` zwraca `suggestion_wording=True` (korekty jako „sugestie”) do czasu bramy F8.
3. **Idempotencja**: ledger tury (`turn_meta.applied_at`), unikalne klucze (`observation_dedupe`, `attempt.dedupe_key`), stany pochodne liczone od nowa z prób/obserwacji (BKT replay, `error_log`), FSRS tylko przy nowej próbie, jedna transakcja. Testy: ponowna analiza, awaria przed zapisem ledgera, rollback, powtórka próby zadania, powtórka testu trwałości.
4. **Poprawna ≠ nieoceniona/przerwana/odrzucona**: `turn_meta.eval_status` (`evaluated|unrated|aborted|rejected`); tylko `evaluated` wchodzi do ocen i dowodów; `evaluated` z 0 obserwacji = poprawna. Dowody pozytywne (`t`) i komunikatywność walidowane tak samo jak błędy: dosłowny cytat w formie końcowej, znana umiejętność będąca celem lekcji, brak w fałszywym starcie, brak przy niskiej pewności STT; `cm` bez cytatu = `na`.
5. **Spójność progów/pul/dowodów**: wszystkie progi i wymagane dowody w `rubric.yaml`; ocena F = min(tempo, pauzy) (brak luk między progami); pula `retention` rozłączna z `practice` (walidator); ocena G/V/N < 4 bez cytatu = `insufficient_evidence` (`no_citation`), a nie błąd ucznia; mianowniki tylko z wypowiedzi `evaluated`.
6. **Nic `human_reviewed`**: statusy w repo bez zmian po F3; fixtury testowe `xx` są `draft`, a testy podnoszą statusy **tylko w pamięci** (`tests/helpers.promote`).
7. **Zależności**: tylko `pyproject.toml` (`PyYAML`, `fsrs`).

## Odstępstwa od specyfikacji (z uzasadnieniem)
- Migracja 003: `correction_style DEFAULT 'summary'` i `UPDATE … SET 'summary'` dla wszystkich (spec: `periodic`, `immediate→periodic`) – decyzja 2. Dotychczasowe `immediate` było wartością domyślną, nie wyborem.
- `turn_meta` ma dodatkowe kolumny (`eval_status`, `comm_quote`, `model`, `prompt_version`, `applied_at`), `attempt.dedupe_key`, unikalny indeks `observation` – idempotencja (decyzje 3–4).
- TurnEval: dodany `cq` (cytat-dowód komunikatywności); spec §2.1 wymaga cytatu, §3.4 go nie przewiduje.
- §2.9 vs §4.6: „sev 1, pierwsze wystąpienie → tylko error_log” rozumiem jako „bez korekty”; BKT dla zliczanego błędu z przypisaną umiejętnością-celem aktualizuje się zgodnie z §4.6.
- Błędy poza celami lekcji nie mają `skill_id` (nie zgadujemy): trafiają do `error_log`, nie do BKT.
- `stt_suspect` także dla brzegów wypowiedzi (sygnał 3 z §2.5), choć reguła 5 w §2.3 go nie wymienia.
- Interpretacja okna planera θ…θ+0,5: poziom k, którego przedział [k−0,5; k+0,5) przecina [θ; θ+0,5].
- `a/an` traktowane jako ten sam wariant przy porównaniu par (a flat → an apartment).
- Porażka testu trwałości zapisuje znacznik `relapse_reset` w `attempt`, by stara historia nie zwracała od razu `mastered`.

## Otwarte ryzyka
- **Treść**: 0 zadań `human_reviewed`; diagnoza `verified` i testy trwałości niedostępne (brama T-CONTENT-2: brakuje 300 zrecenzowanych zadań; brak puli `retention`).
- **Wstępne dopasowanie**: 3 zadania/komórka, ≤10 pytań, trudności nieskalibrowane; sufit „C1 lub wyżej”.
- **Jakość oceny Bielika niezmierzona** (benchmark F8); do tego czasu `summary` domyślnie.
- Symulacje dowodzą spójności, nie trafności; IRT wymaga ≥200 odpowiedzi/zadanie.
- `ingest` zakłada, że F5 poda `goals` lekcji, `theta` obszarów i `now`; kolejka/anulowanie/`NEEDS_EVAL` (ocena niejednoznacznej próby) nie istnieją do F5.
- Zapis recenzji przepisuje YAML (bez komentarzy w treści zadań).
- Kontrola bezpieczeństwa wykonana ręcznie (grep sekretów, parametryzowane SQL, `yaml.safe_load`, walidacja ścieżek w `append_draft`); `/security-review` agentowego nie uruchamiano.
