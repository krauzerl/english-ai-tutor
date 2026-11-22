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

## Wyniki testów (`.venv/bin/pytest`: **94 passed, 1 skipped, 5 deselected(live)**; `ruff check`: czysto)
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
| **Live** (`pytest -m live`, 5 testów) | **NIEWYKONANE**: Ollama wyłączona (próba uruchomienia `ollama serve` zablokowana przez uprawnienia), brak `GEMINI_API_KEY` |

Testy automatyczne nie wykonują żadnych prawdziwych wywołań: Ollama = lokalny serwer HTTP w teście, Gemini = atrapa klienta SDK.

## Zużycie zasobów
Rzeczywiste: zero (brak wywołań modeli). Szacunki: rezerwa na wiejście ≤ okno − odpowiedź; pamięć ≤3000 tok; Bielik 11B Q4_K_M na 8 GiB VRAM — czas/VRAM do zmierzenia w testach live. Koszt Gemini zależy od cennika wpisanego przez użytkownika; kod nie zakłada żadnych stawek ani limitów darmowych.

## Przykładowe działanie
Nieuruchomione live. Zachowanie odwzorowane w testach (kształt odpowiedzi SDK Gemini zgodny z zainstalowanym `google-genai` 3.6.1: `usage_metadata.prompt/candidates/thoughts_token_count`, `GenerateContentConfig.response_json_schema`).

## Otwarte problemy / założenia do weryfikacji live
1. **Live niewykonany** – potrzebne: `ollama serve` (lub `sudo systemctl enable --now ollama`, decyzja użytkownika), klucz w `~/.config/english-ai-tutor/.env`, `GEMINI_LIVE_MODEL`, cennik i limity w `config.toml`.
2. Założenie: `max_output_tokens` Gemini obejmuje tokeny rozumowania (limit górny kosztu). Jeśli nie — koszt może przekroczyć szacunek; do sprawdzenia live, ewentualnie ustawić `thinking_budget`.
3. `shortcut`: brak rezerwacji budżetu przy żądaniach równoległych (jeden użytkownik, jeden wątek).
4. Szacowanie tokenów bez korekty z `usage` providera (tylko stały konserwatywny współczynnik).
5. Fallback strumienia tylko przed pierwszym fragmentem; po awarii w trakcie UI dostaje `StreamInterrupted` i sam decyduje o ponowieniu (wraca od zera, bez sklejania).
6. Brak retencji `llm_usage`; po usunięciu profilu zostają wiersze bez treści i bez profilu.
7. Eksport profilu zawiera wiersze `llm_usage` tego profilu (bez treści).
8. Granice dnia/miesiąca w UTC.
9. Docelowe schematy Pydantic (`TurnFeedback`, `RubricScore`) i prompty — F4/F5.
