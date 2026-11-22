# Moduł 02 – Warstwa modeli AI (F2): raport

Gałąź `feat/f0-scaffold`. Zakres: tylko F2. Bez GUI, STT, TTS, silnika dydaktycznego, SessionService. Bez push.

## Wykonane zmiany
- `tutor/llm/base.py`: `Message`, `Usage` (in/out/reasoning), `Reply`, wyjątki (`LLMError` z `user_message` dla UI; `LLMTimeout`, `LLMUnavailable`, `ConsentRequired`, `LimitsNotConfigured`, `BudgetExceeded`, `InvalidStructuredOutput`, `StreamInterrupted(partial)`, `ContextTooLarge`), `CancelToken`, `Stream` (anulowanie, hook końca, kontrola zgody przed każdym fragmentem), protokół `LLMProvider`, `LocalFallback`.
- `ollama.py`: `/api/chat` (przeniesione z `main.py`), `options.num_predict/num_ctx`, `format`=JSON schema, strumień NDJSON, anulowanie zamyka połączenie, timeout, usage z `prompt_eval_count/eval_count`. Domyślnie Bielik 11B; model dowolny z config.
- `gemini.py`: SDK `google-genai`, model wymagany z config (brak domyślnego), `response_json_schema`, `thoughts_token_count` jako `reasoning_tokens`, opcjonalny `thinking_budget`. Komunikaty błędów własne (tekst wyjątku SDK nigdy nie trafia do UI/logów), klucz poza `repr`.
- `structured.py`: JSON → Pydantic; 1 retry; `InvalidStructuredOutput` bez treści modelu; błędy providera bez retry.
- `context.py`: `estimate_tokens` = znaki/3 (zachowawczo), `build_context` (system + pamięć ≤3000 tok + bieżąca wiadomość + rezerwa; okno modelu jako limit całości), checkpoint ≤300 tok + poprzednie podsumowanie sesji + ogon tur po checkpoincie, `needs_checkpoint` / `make_checkpoint(summarize)` (LLM wstrzykuje wywołujący; brak SessionService).
- `meter.py`: `Meter` (limity dzienny/miesięczny, UTC, **wspólne dla wszystkich profili**, ostrzeżenie ≥80%, blokada gdy wydane + maks. koszt żądania > limit), `Guarded` (zgoda profilu sprawdzana przy każdym żądaniu i przy każdym fragmencie strumienia, limity, zapis `llm_usage`; po błędzie/anulowaniu zapis szacunku).
- `tutor/llm/__init__.py`: `llm_settings`, `build_provider(role)`, `build_meter`, `context_window`. Provider/model wybierane per rola (conversation/evaluation/generation) w `config.toml`.
- Migracja `002`: `llm_usage.profile_id` → `ON DELETE SET NULL`, żeby usunięcie profilu nie zerowało wspólnego limitu (wiersze nie zawierają treści).
- `config.py`: `set_last_profile` zachowuje resztę pliku (wcześniej nadpisałby sekcje `[llm]`/`[limits]`); `gemini_api_key()` z env lub `~/.config/english-ai-tutor/.env`.
- `Repo`: `add_llm_usage`, `llm_cost_since`. `.gitignore`: poprawiona sklejona linia (`.env` wcześniej NIE było ignorowane). `pyproject`: zależności `pydantic`, `google-genai`, marker `live`, ruff line-length 120 (testy: E501/E702 ignorowane).

Przykład `config.toml`:
```toml
[llm.conversation]
provider = "ollama"
model = "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M"
[llm.evaluation]
provider = "gemini"
model = "<nazwa modelu z konta>"
[limits]
daily_usd = 0.50
monthly_usd = 5.00
[pricing."<nazwa modelu z konta>"]   # wpisz z aktualnego cennika Google
in_per_mtok = 0.0
out_per_mtok = 0.0
[context_windows]
"<model>" = 32768
```

## Wyniki testów (`.venv/bin/pytest`: **104 passed, 1 skipped, 5 deselected(live)** po domknięciu; `ruff check`: czysto)
| Test | Wynik |
|---|---|
| T-LLM-1 zły JSON → 1 retry → wyjątek, bez zapisu | zaliczony |
| T-LLM-2 zła kategoria / poziom spoza A1–C2 / brak pola | zaliczony (model testowy; docelowe schematy w F4/F5) |
| T-LLM-3 timeout/brak Ollamy → kontrolowany błąd z `user_message` | zaliczony na poziomie dostawcy; pełny przepływ „tura zachowana" **ODROCZONY (F5, SessionService)** – test oznaczony skip |
| T-LLM-4 fallback sygnalizowany; brak zgody → chmura zablokowana (0 żądań) | zaliczony |
| T-LLM-5 100% → blokada przed wywołaniem; ≥80% → ostrzeżenie; miesięczny; wspólny dla profili; przeżywa usunięcie profilu | zaliczony |
| T-LLM-6 200 tur: wejście ≤ budżet, pamięć ≤3000, 20 checkpointów | zaliczony |
| T-LLM-7 zmiana providera: historia/profil bez zmian | zaliczony (SRS jeszcze nie istnieje) |
| T-LLM-8 klucz/treść nie w logach, DB, eksporcie; brak klucza w repo; `.env` ignorowany; klucz usuwany z błędów SDK | zaliczony |
| T-ISO-4 kontekst A bez danych B (także cudza sesja podana przy własnym profilu) | zaliczony |
| Dodatkowe: anulowanie streamingu (Ollama real HTTP, Gemini), cofnięcie zgody (między żądaniami i w trakcie strumienia), przełączanie modeli/ról, awaria w trakcie streamingu (bez łączenia), nigdy lokalny→chmura, migracja 001→002 na realnej bazie v1 | zaliczone |
| Regresja F0/F1 (22 testy) + `main.py --cli` | zaliczone |
| **Live Ollama** (`pytest -m live`, 3 testy: chat+usage, stream+anulowanie, structured) | **zaliczone** na Bieliku 11B (2026-11-22, po domknięciu) |
| **Live Gemini** (2 testy) | **ODROCZONE** jawnie (skip „ODROCZONE: Gemini nieskonfigurowany”): brak `GEMINI_API_KEY`, `GEMINI_LIVE_MODEL`, cennika i limitów |

Testy automatyczne nie wykonują żadnych prawdziwych wywołań: Ollama = lokalny serwer HTTP w teście, Gemini = atrapa klienta SDK.

## Zużycie zasobów (pomiar live, `tests/live/bench_ollama.py`; Ryzen 7 3700X, 31 GiB RAM, RTX 2060 SUPER 8 GiB, Ollama 0.9.0; VRAM bazowy pulpitu ≈ 0,6 GiB)
| Model | start „na zimno” | czat 120 tok | TTFT strumienia | tok/s | VRAM modelu | RAM (RSS ollama) | anulowanie | structured |
|---|---|---|---|---|---|---|---|---|
| Bielik 11B v2.3 Q4_K_M | 2,8 s | 7,0 s (105 wej / 75 wyj) | 0,10 s | **11,3** | 6937 MiB z 9147 MiB (≈2,2 GiB na CPU) | ≈7,4 GiB | 0,31 s | 1,25 s, poprawny |
| Bielik 7B v0.1 Q4_K_S | 4,1 s | 1,1 s (45 / 67) | 0,03 s | **64,0** | 6075 MiB (w całości na GPU) | ≈0,7 GiB | 0,04 s | 0,28 s, poprawny |
Wnioski: 11B nie mieści się w 8 GiB VRAM (częściowy offload, ~11 tok/s — wystarcza do czatu, wolno do ocen wsadowych); 7B jest ~6× szybszy. 11B + Whisper na GPU nadal wykluczone (patrz HANDOFF). Modele zwolnione po pomiarze (`keep_alive: 0`). Gemini: zużycie niezmierzone (odroczone); koszt liczony z cennika wpisanego przez użytkownika.

## Przykładowe działanie
- Ollama (live): czat, streaming z anulowaniem po pierwszym fragmencie (0,31 s do zatrzymania, `cancelled=True`), odpowiedź strukturalna zwalidowana Pydantic — Bielik 11B i 7B.
- Gemini: tylko atrapa SDK (kształt odpowiedzi zgodny z `google-genai` 3.6.1). Live odroczone.

## Domknięcie (kolejna iteracja F2)
- **Budżet i współbieżność:** `Meter.reserve` w `BEGIN IMMEDIATE` sprawdza limity i wpisuje rezerwację (wiersz `llm_usage` z kosztem maks.); `settle` zamienia ją na rzeczywiste zużycie (także po błędzie/anulowaniu → szacunek wejścia). Rezerwacje innych połączeń/procesów liczą się do wydatków. Test: 8 wątków × osobne połączenia, limit na 2 żądania → dokładnie 2 przechodzą (przed poprawką przechodziło 8/8). Wybrano blokadę SQLite zamiast mutexu w procesie, bo chroni też przed drugim procesem.
- **Koszt Gemini:** według dokumentacji Google (ai.google.dev, pricing i opis tokenów) tokeny rozumowania są rozliczane jak wyjście i wliczają się do `max_output_tokens`; rezerwacja = wejście + `max_tokens` pokrywa więc odpowiedź + rozumowanie. Rzeczywisty koszt (`candidates + thoughts`) zapisywany w całości; przekroczenie rezerwacji jest logowane. Założenie zweryfikowane tylko z dokumentacji, nie live.
- **Cennik:** `Price` odrzuca zero/ujemne/NaN; brak lub zero w `[pricing]` → `LLMError`, nie „darmowy”. Brak cennika modelu zewnętrznego → `LimitsNotConfigured`.
- **Historia Git (`git log --all`, wszystkie blobry):** 0 plików SQLite (sprawdzony nagłówek każdego bloba), 0 plików `.env/.db/.bak/.wal/.pem/.key`, 0 trafień wzorców kluczy/tokenów. Błąd `.gitignore` (`.env*.egg-info/` w commicie F0+F1 zamiast `.env` i `*.egg-info/`) istniał, ale żaden plik `.env` nigdy nie trafił do historii; jedyną konsekwencją było śledzenie `egg-info/` (usunięte z indeksu, zostaje w historii; nie jest wrażliwe).

## Otwarte problemy / założenia do weryfikacji live
1. **Gemini live odroczone** – potrzebne: klucz w `~/.config/english-ai-tutor/.env`, `GEMINI_LIVE_MODEL`, cennik i limity w `config.toml`; przy pierwszym live sprawdzić założenie o `max_output_tokens` i pomiar `thoughts_token_count`.
2. Założenie z dokumentacji: `max_output_tokens` obejmuje rozumowanie. Gdyby live temu przeczyło — koszt może przekroczyć rezerwację (jest wtedy logowane); wtedy ustawić `thinking_budget` i rezerwować `max_tokens + thinking_budget`.
3. Osierocona rezerwacja po crashu zostaje jako koszt maksymalny (bezpieczna strona); brak sprzątania. Połączenie SQLite jest per wątek (`check_same_thread`) — GUI musi otwierać własne.
4. Szacowanie tokenów bez korekty z `usage` providera (tylko stały konserwatywny współczynnik).
5. Fallback strumienia tylko przed pierwszym fragmentem; po awarii w trakcie UI dostaje `StreamInterrupted` i sam decyduje o ponowieniu (wraca od zera, bez sklejania).
6. Brak retencji `llm_usage`; po usunięciu profilu zostają wiersze bez treści i bez profilu.
7. Eksport profilu zawiera wiersze `llm_usage` tego profilu (bez treści).
8. Granice dnia/miesiąca w UTC.
9. Docelowe schematy Pydantic (`TurnFeedback`, `RubricScore`) i prompty — F4/F5.

## Publikacja (przegląd przed push)
- Remote: `origin` = github.com/krauzerl/english-ai-tutor; push gałęzi `feat/f0-scaffold`, bez force, bez scalania do `main`.
- Przegląd całej historii (`git log --all`): brak plików `.db/.sqlite/.bak/.wal/.env/.pem/.key`, brak katalogów backupów/eksportów, brak wzorców kluczy (AIza…, sk-…, ghp_…, klucze prywatne). Jedyne trafienie: atrapa `abc123` w teście. Brak danych uczniów (testy używają baz w `tmp_path`).
- Usunięto z indeksu `english_ai_tutor.egg-info/` (artefakt builda, wcześniej śledzony; teraz w `.gitignore`).
- Ponowny przebieg: 94 passed, 1 skipped, 5 deselected (live); `ruff check` czysty.
