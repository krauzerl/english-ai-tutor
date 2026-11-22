# Instrukcja dla Sonnet – implementacja F3 i F4

Kontekst: repo `english-ai-tutor`, start z gałęzi `feat/pedagogy-design`. Moduły 01–04 zaakceptowane. **Nie powtarzaj audytu ani projektu.** Projekt jest w `04_PEDAGOGY_SPEC.md` — to źródło prawdy; przy sprzeczności z innym dokumentem wygrywa spec 04, a sprzeczność zgłoś w raporcie.

## Czytaj w tej kolejności
1. `HANDOFF.md` (stan, środowisko, decyzje).
2. `04_PEDAGOGY_SPEC.md` całość, szczególnie §5 (F3), §2–§4 i §6–§8 (F4), §11 (odbiór).
3. `TEST_PLAN.md` §4 (identyfikatory testów).
4. Kod: `tutor/store/db.py` (runner migracji), `tutor/store/repo.py`, `tutor/llm/structured.py`, `tests/conftest.py`, `tests/llm_fakes.py`.

## Zasady pracy
- Gałęzie: `feat/f3-content` z `feat/pedagogy-design`, potem `feat/f4-pedagogy` z `feat/f3-content`. Push dopiero po kontroli sekretów; **nie scalaj do `main`**.
- TDD (`superpowers:test-driven-development`): najpierw test z identyfikatorem z TEST_PLAN, potem kod. Na końcu `superpowers:verification-before-completion`.
- Minimalizm (Ponytail): bez nowych zależności poza `fsrs` i `PyYAML` (sprawdź, czy są w `requirements.txt`; dopisz brakujące). Bez abstrakcji „na później”.
- `tutor/pedagogy/` nie importuje `tutor.llm`, `tutor.voice`, `tutor.ui`, `requests`. Czas (`now`) i ziarno losowe jako parametry.
- Środowisko: tylko `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/ruff`. Testy nie wołają prawdziwych modeli (live tylko z `-m live`).
- Nie zmieniaj `tutor/voice/` (moduł głosowy zamknięty; `transcribe_detailed()` należy do F5).
- Dokumenty i komentarze po polsku, jak reszta repo.
- Katalog treści fizycznie: `tutor/content/<lang>/` (ARCHITECTURE §2); spec pisze skrótowo `content/<lang>/`. Dodaj do `package-data` w `pyproject.toml`.

## F3 – treść (zakres zamknięty)
1. `tutor/pedagogy/content.py`: modele pydantic dla skills, items, errors, variants, stt_confusables, disfluency, rubric, scenarios, reviewers (§5.1–§5.4); `load(lang)`, `validate(lang) -> raport`; graf prerekwizytów (acykliczność).
2. CLI w `tutor/cli.py`: `content validate <lang>` (liczności per obszar × poziom × status, błędy z numerem linii/ID) i `content review <lang>` (interaktywny: pokaż zadanie, `a`kceptuj/`e`dytuj notatkę/`o`drzuć/`p`omiń; zapisuje `review.status`, `reviewer` z `reviewers.yaml`, `reviewed_at`). Tylko ta komenda ustawia `human_reviewed`.
3. `content/en/`: `skills/{grammar,general,conversation,tech_it,interview}.yaml` (≥80 umiejętności, własne parafrazy can-do, bez kopiowania English Profile/EVP), `errors.yaml` (rdzeń z §4.9 + podkategorie EN + szablony PL: wyjaśnienie, L1, L2, L3), `variants.yaml`, `stt_confusables.yaml`, `disfluency.yaml`, `rubric.yaml` (progi §2.2, BKT §4.6, FSRS `fast_ms`), `reviewers.yaml` (pusta lista z komentarzem), `scenarios/` (5, w tym rekrutacja IT), `prompts/` (`turn_eval.md` zgodny ze schematem §3.4, `rubric_eval.md`, `report_narrative.md`, `gen_item.md`, `solve_item.md`, każdy z `prompt_version`), `grammar/` (wyjaśnienia PL tylko dla umiejętności użytych w pilotażu).
4. Bank pilotażowy: dokładnie 3 zadania na (grammar, vocabulary, reading, listening) × (A1, A2, B1, B2, C1) = 60. Mieszanka typów i domen. Napisane przez Ciebie = `provenance.source: ai_generated`, `review.status: draft` (albo `ai_checked` tylko jeśli faktycznie przeszło kontrolę na ślepo skryptem). **Nigdy `human_reviewed`.**
5. `tools/gen_items.py`: generacja przez `structured()` (rola `generation`) → walidator → zapis tylko jako `draft`; opcja `--solve-check` (rola `evaluation`, rozwiązywanie na ślepo → `ai_checked`/`rejected`). Testy na FakeProvider. Nie uruchamiaj masowej generacji.
6. Testy: T-CONTENT-1, -3, -4, -5, T-ARCH-2.
7. DoD F3: `content validate en` czyste; pytest + ruff zielone; raport `docs/ai-work/05_F3_CONTENT_REPORT.md` (liczności, czego brakuje do bramy T-CONTENT-2, lista decyzji).

## F4 – rdzeń dydaktyczny
1. `tutor/store/migrations/003_pedagogy.sql` dokładnie wg §7 (tylko `ALTER TABLE … ADD COLUMN` + nowe tabele). **Nie przebudowuj `profile`** — runner działa z `foreign_keys=ON` w transakcji, `DROP TABLE profile` skasowałby kaskadowo dane. Metody repo dla `observation`, `turn_meta`, nowych kolumn; każda z `profile_id`. Test T-DB-3 przed migracją.
2. Moduły wg tabeli §8, w kolejności: `cefr` → `diagnosis` → `mastery` → `srs` → `retention` → `errors` → `schemas` → `assessment` → `fluency` → `correction` → `planner` → `report`.
3. Wskazówki:
   - `diagnosis`: siatka numpy-free (lista floatów wystarczy), wzory §4.2; stan serializowalny do JSON (wznowienie). Sufit/podłoga §4.3.
   - `assessment.classify`: kolejność reguł §2.3 dosłownie; zwraca także odrzucone z `drop_reason`.
   - `correction`: maszyna stanów L1–L4, polityka trybów i priorytet §3.1–§3.2; bez wywołań LLM (sprawdzenie niejednoznacznej próby zwraca `NEEDS_EVAL`, obsłuży `app/` w F5).
   - `report`: wejście = dane z DB w dataclassach; wyjście = JSON raportu + `validate_narrative(text, report_json)`.
   - Parametry liczbowe tylko z `rubric.yaml`, nie stałe w kodzie (poza wartościami domyślnymi testów).
4. Testy: T-PED-1..10, T-RET-1/2, T-ASSESS-1..7, T-CORR-1..3, T-ERR-1, T-REPORT-1..3, T-DB-3, T-LANG-1 (syntetyczny pakiet `tests/fixtures/content/xx/`), T-ARCH-1, T-ISO po nowych tabelach.
5. DoD F4: kryteria §11 spełnione i sprawdzone poleceniami; raport `docs/ai-work/06_F4_PEDAGOGY_REPORT.md` (co zrobione, wyniki symulacji z zastrzeżeniem §4.4, odstępstwa od specyfikacji z uzasadnieniem, otwarte ryzyka). Aktualizacja `HANDOFF.md` (status).

## Czego nie robić
Integracja z rozmową/kolejką oceny (F5), GUI, pełny bank zadań, C2, ocena wymowy, Gemini, zmiany w `tutor/voice/`, scalanie do `main`, oznaczanie czegokolwiek jako zweryfikowanego przez człowieka.

## Przed push
`git diff feat/pedagogy-design... | grep -inE 'api[_-]?key|secret|token|password|@[a-z0-9-]+\.[a-z]'` — przejrzyj trafienia; żadnych plików `.env`, baz `.db`, nagrań, ścieżek domowych z danymi ucznia.
