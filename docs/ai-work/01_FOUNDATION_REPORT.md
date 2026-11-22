# Moduł 01 – Fundament (F0 + F1): raport

Gałąź: `feat/f0-scaffold`. Zakres: tylko F0 + F1. Brak GUI, LLMProvider, silnika dydaktycznego, mowy.

## Wykonane zmiany
- F0: `pyproject.toml` (Python ≥3.12, dep: `requests`; dev: `pytest`, `ruff`), pakiet `tutor/`, `tests/`, instalacja editable w istniejącym `.venv`. Usunięto puste `ollama_client.py`, `prompts.py`.
- `main.py`: logika czatu bez zmian, tylko owinięta w `chat()`. Bez argumentów i z `--cli` działa jak dotąd. Nowe: `main.py profile create|list|select|export|delete`.
- F1: SQLite (`tutor/store/db.py`), migracja `001_init.sql`, `Repo` (`tutor/store/repo.py`), ścieżki XDG i `config.toml` (`tutor/config.py`), CLI profili (`tutor/cli.py`).
- Migracje: `PRAGMA user_version`, pliki `NNN_*.sql`, każda w transakcji z rollbackiem, odmowa startu na bazie nowszej niż kod, backup (API `sqlite3.backup`, spójny przy WAL) przed migracją istniejącej bazy.
- Uprawnienia: katalogi 0700, baza/-wal/-shm/backup/config.toml/eksport 0600 (umask 077 przy tworzeniu + chmod).

## Decyzje architektoniczne
1. **Własność na poziomie SQLite**: `UNIQUE(id, profile_id)` na `session`, `UNIQUE(id, session_id, profile_id)` na `turn`; `turn`, `checkpoint`, `attempt`, `session_summary` mają klucze złożone do rodzica. `checkpoint.upto_turn_id` wskazuje turę tej samej sesji i profilu. Brak `ON UPDATE CASCADE`, więc zmiana `profile_id` rodzica z dziećmi jest odrzucana.
2. **`session_summary`**: własny `id`; `session_id` NULL dla week/month; `period_start` dla week/month. CHECK wiąże poziom z kolumnami; częściowe UNIQUE: jedno podsumowanie na sesję i jedno na (profil, poziom, okres). Stary PK `session_id` wykluczał podsumowania tygodniowe. Generowania brak.
3. **Historia prób**: `attempt` bez UNIQUE; kolumna generowana `day`; indeks `(profile_id, skill_id, created_at)`; `Repo.attempt_days` zwraca różne dni (baza pod regułę „≥2 różne dni”). `created_at` można podać jawnie (testy, import).
4. **Dane globalne**: tabel `skill`/`item` nie ma w bazie ucznia (odstępstwo od ARCHITECTURE §3). Treść ma żyć w `content/<lang>/` (F3); `skill_id`/`item_id` w danych ucznia to teksty bez FK. Usunięcie profilu i eksport nie mogą dotknąć treści globalnej. Jeśli F3 zechce indeks w SQL, ma to być osobny plik/baza.
5. `student_tables()` z introspekcji (`profile_id` w kolumnach): eksport, usuwanie i testy obejmują każdą przyszłą tabelę ucznia automatycznie.
6. Bez ORM, bez dodatkowych warstw: jedna klasa `Repo`. Metody ucznia przyjmują `profile_id` i go filtrują; tabele bez metod w repo (competence, srs_card, diagnosis_run, next_plan, llm_usage) dostaną je w modułach, które ich używają.
7. „Wybór” profilu = `last_profile_id` w `config.toml`.
8. `synchronous=NORMAL` przy WAL (trwałość po crashu aplikacji; przy utracie zasilania możliwa utrata ostatnich transakcji, baza spójna).

## Zmodyfikowane / dodane pliki
Zmienione: `main.py`, `.gitignore`, `docs/ai-work/HANDOFF.md`. Usunięte: `ollama_client.py`, `prompts.py`. Nowe: `pyproject.toml`, `tutor/{__init__,config,cli}.py`, `tutor/store/{__init__,db,repo}.py`, `tutor/store/migrations/001_init.sql`, `tests/{conftest,test_smoke,test_db,test_isolation,test_profiles,test_legacy_cli}.py`, ten raport.

## Wyniki testów (`.venv/bin/pytest`: 22 passed; `ruff check`: czysto)
| Test | Wynik |
|---|---|
| T-DB-1 migracja z pustej / z n-1 + backup (0600) | zaliczony (na sztucznych migracjach 001/002) |
| T-DB-1+ rollback nieudanej migracji; odmowa bazy nowszej | zaliczony |
| T-DB-2 `foreign_keys=ON`, WAL | zaliczony |
| T-ISO-1 repo nie zwraca danych drugiego profilu (wszystkie metody odczytu) | zaliczony |
| T-ISO-2 kasowanie kaskadowe: 0 wierszy A we wszystkich tabelach, B nietknięty, `foreign_key_check` pusty | zaliczony |
| T-ISO-3 eksport nie zawiera danych B | zaliczony |
| T-ISO-4 kontekst LLM bez danych B | **ODROCZONY** (brak `llm/context.py`, F2) |
| Powiązanie rekordów różnych profili (turn, attempt, checkpoint, summary; UPDATE właściciela) | zaliczony: `IntegrityError` |
| Trwałość po ponownym otwarciu bazy; `profile list` po restarcie procesu | zaliczony |
| Integralność eksportu (JSON round-trip, wszystkie tabele, tylko własne id) | zaliczony |
| Klucze `session_summary`, historia prób w różnych dniach | zaliczony |
| Uprawnienia plików/katalogów (db, wal, shm, backup, config, eksport) | zaliczony; potwierdzone też ręcznie na realnych ścieżkach |
| Istniejące CLI | zaliczony na atrapie `requests.post` (żądanie identyczne) + `echo exit \| main.py --cli`. **Nie** sprawdzone na żywej Ollamie (serwis wyłączony) |

## Otwarte problemy
- Realny T-DB-1 „od n-1” zadziała dopiero przy pierwszej migracji 002; dziś zweryfikowany mechanizm na migracjach testowych.
- Backupy bez retencji (rosną przy każdej migracji).
- Eksport zawiera pełny tekst rozmów i odpowiedzi (wrażliwe); plik 0600, ale poza nim użytkownik odpowiada.
- Usuwanie audio (RQ-1.3) niezaimplementowane: audio nie jest zapisywane; do zrobienia w F7.
- Brak ścisłej kontroli typów `score`/`correct` poza CHECK; walidacja domenowa w F4.
- `ruff format` nie zastosowany (tylko `ruff check`).
- Ollama nadal wyłączona/0.9.0; bez zmian, wymaga decyzji użytkownika (sudo).
- Pytania z HANDOFF (klucz Gemini, recenzent zadań, BrE/AmE, nagrania audio) nadal otwarte.
