# F3 – treść (raport)

Gałąź `feat/f3-content` (z `feat/pedagogy-design`, `1d153a5`). Źródło prawdy: `04_PEDAGOGY_SPEC.md` + decyzje nadrzędne użytkownika (poniżej). Nic nie scalono do `main`.

## Co powstało
- `tutor/pedagogy/content.py`: modele pydantic (skills, items, errors, variants, stt_confusables, disfluency, rubric, scenarios, reviewers), `load`, `validate` (błędy z plikiem:linią i ID), graf prerekwizytów (cykle), `answer_ok`/`expand_answers` (warianty), brama statusów `usable`/`select_items`, `diagnosis_gate`, `retention_gaps`, zapis statusów (`set_review` – ścieżka człowieka, `set_ai_check` – ścieżka AI, `append_draft` – generator).
- `main.py content validate <lang>` i `content review <lang> --reviewer <id>` (`tutor/cli.py`).
- `tools/gen_items.py`: generacja (rola `generation`, `structured()`, walidator, zapis tylko `draft`, `--n ≤ 5`) i `--solve-check` (rola `evaluation`, na ślepo).
- `tutor/content/en/`: 115 umiejętności w 5 domenach, `errors.yaml` (49 kategorii z szablonami PL L1/L2 + wyjaśnienie), `variants.yaml` (28 grup), `stt_confusables.yaml`, `disfluency.yaml`, `rubric.yaml`, `reviewers.yaml` (pusty), 5 scenariuszy (w tym rekrutacja IT), 5 promptów z `prompt_version`, 15 wyjaśnień PL (tylko umiejętności z pilotażu).
- Bank pilotażowy: 60 zadań = 3 × (grammar, vocabulary, reading, listening) × (A1–C1); 6 typów, 5 domen.
- Zależności: `PyYAML`, `fsrs` dopisane wyłącznie do `pyproject.toml` (decyzja 7); `tutor.content` w `package-data`.

## Liczności (po `content validate en`)
Umiejętności: 115. Zadania: 60 – `ai_checked`: 49, `draft`: 11, `human_reviewed`: **0**, `rejected`: 0 (szczegóły per obszar × poziom w wyniku komendy).

Kontrola na ślepo wykonana naprawdę (skrypt `--solve-check`, Bielik 11B lokalnie, 60 wywołań, 2 min 17 s, koszt 0). Niezgodność → status zostaje `draft` z notatką `solve_check: niezgodność z kluczem` (11 zadań). Nie badałem przyczyn: możliwe, że to słabość Bielika w EN lub format odpowiedzi, a nie błąd zadania. Te 11 trafi do przeglądu człowieka.

## Brama T-CONTENT-2 (diagnoza właściwa) – czego brakuje
Wymagane ≥ 15 `human_reviewed` na (obszar × poziom A1–C1) = 300 zadań. Jest 0 zrecenzowanych i 3 zadania na komórkę. Do bramy brakuje 300 zadań (≈ 240 do dopisania po 12/komórkę + 300 recenzji). `diagnosis_gate()` zwraca `open=False`. Testy trwałości: żadna umiejętność nie ma puli `retention` (`retention_gaps` zwraca wszystkie) – pilotaż ma pule `diagnosis`+`practice`.

## Decyzje i odstępstwa
1. **Decyzja 1 (użytkownik): wstępne dopasowanie z `ai_checked`.** `usable(item, "placement")` dopuszcza `human_reviewed` i `ai_checked`; `diagnosis`/`retention`/`cefr_check` wyłącznie `human_reviewed` (ścisła brama). Rozróżnienie wprowadzone w treści (F3); algorytm i oznaczenie wyniku w F4.
2. **Decyzja 5: pule.** Walidator wymusza rozłączność `retention` i `practice` w obrębie zadania; `retention` nigdy nie jest w `practice`. Dodatkowo test trwałości wyklucza w F4 zadania widziane w `attempt`. Wszystkie progi rubryki i wymagane dowody są w `rubric.yaml` (jedno źródło).
3. **Decyzja 6:** brak jakiegokolwiek `human_reviewed`; `reviewers.yaml` pusty (test `test_content_3_no_human_reviewed_in_repo`). Autor treści (AI) w `provenance.model: claude-sonnet-5-5`.
4. Spec §5.3 mówi „rejected lub draft z notatką” przy niezgodności; wybrałem `draft` (z `--reject-on-mismatch` opcjonalnie), bo słaby model sędziowski nie powinien trwale odrzucać dobrych zadań. Odstępstwo od brief (`ai_checked/rejected`).
5. Pole `stimulus` w zadaniu (tekst do czytania) – spec §5.2 nie ma miejsca na tekst `reading_mc`.
6. `reviewer`/`reviewed_at` dopuszczone także dla `rejected`/`suspect` (decyzja człowieka); zabronione dla `draft`/`ai_checked`.
7. Walidator sprawdza zgodność obszaru zadania z obszarem umiejętności, duplikaty (prompt+tekst+audio), PII (e-mail/URL/telefon) i długość promptu wg poziomu (`rubric.limits`).
8. `programme/program` ma `skip_domains: [tech_it]`.
9. `content review` obsługuje zadania; scenariusze i wyjaśnienia mają status `draft`, ale nie ma jeszcze dla nich ścieżki przeglądu (YAGNI do czasu recenzenta).
10. Zapis po recenzji przepisuje plik YAML: komentarze wewnątrz plików zadań nie przeżyją (nagłówek `#` zachowany).
11. `requirements.txt` (stary freeze z modułu 02/03) nie zmieniony; źródłem zależności jest `pyproject.toml`.

## Otwarte ryzyka
- Jakość treści nieweryfikowana przez człowieka; 49 `ai_checked` to kontrola słabego modelu, nie recenzja.
- Trudności zadań (`difficulty`) są oszacowaniem autora, nieskalibrowane.
- Pilotaż 3 zadania/komórka: wstępne dopasowanie ma niski zasięg i wysoką niepewność.
