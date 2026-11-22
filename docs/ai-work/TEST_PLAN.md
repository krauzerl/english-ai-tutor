# TEST PLAN

Narzędzia: `pytest`, `pytest-qt`, `FakeProvider` (deterministyczne odpowiedzi LLM z plików fixture). Testy jednostkowe/integracyjne nie wołają prawdziwych modeli. Testy z modelem: znacznik `@pytest.mark.live`, uruchamiane ręcznie.

## 1. Architektura
- T-ARCH-1: `tutor/pedagogy/**` nie importuje `tutor.llm`, `tutor.ui`, `tutor.speech`, `requests` (analiza AST).
- T-ARCH-2: rdzeń (`tutor/` poza `content/`) nie zawiera literałów EN typu słowa ćwiczeń (lista kontrolna słów: brak plików `.yaml` treści poza `content/`).

## 2. Baza danych i izolacja użytkowników
- T-ISO-1: dwa profile; każda metoda repo wywołana z `profile_id=A` nigdy nie zwraca rekordów B (test parametryzowany po wszystkich metodach repo).
- T-ISO-2: usunięcie A usuwa 100% wierszy A we wszystkich tabelach; B nietknięte (zliczanie przed/po).
- T-ISO-3: eksport A nie zawiera żadnego id/tekstu B.
- T-ISO-4: kontekst LLM budowany dla A nie zawiera danych B.
- T-DB-1: migracja od pustej bazy i od wersji n-1; backup utworzony.
- T-DB-2: `foreign_keys=ON`, WAL aktywne.

## 3. LLM
- T-LLM-1: zły JSON → 1 retry → wyjątek `InvalidStructuredOutput`, brak zapisu do DB.
- T-LLM-2: JSON z niedozwoloną kategorią błędu / poziomem spoza A1–C2 → odrzucony.
- T-LLM-3: timeout/ConnectionError Ollamy → komunikat, tura ucznia zachowana.
- T-LLM-4: fallback Gemini → Ollama; brak zgody → Gemini niedostępny nawet z kluczem.
- T-LLM-5: limit dzienny 100% → blokada; 80% → ostrzeżenie.
- T-LLM-6: budżet kontekstu: 200 tur → wejście ≤ budżet; checkpoint utworzony co 10 tur.
- T-LLM-7: zamiana providera w trakcie: historia, profil, SRS bez zmian.
- T-LLM-8: klucz API nie pojawia się w logach, DB, eksporcie (grep).

## 4. Poprawność dydaktyczna (symulowani uczniowie)
Uczeń symulowany = funkcja odpowiadająca poprawnie z prawdopodobieństwem zależnym od różnicy (poziom ucznia − trudność zadania), per obszar.
- T-PED-1: dla uczniów o profilu {vocab B2, grammar A2, …} diagnoza zwraca poziomy w ±1 od prawdy w ≥90% z 500 symulacji; obszary niezależne.
- T-PED-2: przedział niepewności zawiera prawdziwy poziom w ≥90% przypadków; maleje z liczbą zadań.
- T-PED-3: uczeń zawsze poprawny → nie przekracza C2, test kończy się ≤ limit zadań; zawsze błędny → A1, bez pętli.
- T-PED-4: mastery rośnie przy poprawnych, maleje przy błędnych; opanowanie wymaga 2 różnych dni.
- T-PED-5: planer: zaległe powtórki ≤30% czasu; błąd z count≥3 trafia do planu; nie wybiera umiejętności z nieopanowanymi prerekwizytami; suma minut = wybrany czas (15/30/45/60) ±1.
- T-PED-6: test trwałości: umiejętność opanowana 7+ dni temu wraca; porażka obniża p.
- T-PED-7: FSRS: poprawna odpowiedź wydłuża interwał, błędna skraca.
- T-PED-8: warianty poprawne (colour/color, I'm/I am) w zadaniach zamkniętych uznane.
- T-CONTENT-1: każde zadanie: poprawny schemat, istniejący `skill_id`, `cefr`, ≥1 akceptowana odpowiedź, `reviewed: true`.
- T-CONTENT-2: rozkład zadań: ≥15 na (obszar × poziom A1–C1).

## 5. Integracja i regresja
- T-INT-1: sesja 15 min na FakeProvider: plan → ćwiczenia → rozmowa → podsumowanie → `next_plan` zapisane.
- T-INT-2: tryb korekty natychmiastowy vs podsumowujący — te same błędy w `error_log`, różny moment prezentacji.
- T-INT-3: przerwanie sesji (zamknięcie aplikacji) → checkpoint, wznowienie możliwe.
- T-REG: złote pliki (golden) dla promptów: zmiana promptu wymaga aktualizacji `prompt_version`.
- T-UI-1: start bez Ollamy → komunikat w pasku stanu, aplikacja działa (powtórki offline).
- T-UI-2: długie wywołanie LLM nie blokuje pętli zdarzeń (pytest-qt `waitUntil`).
- T-UI-3: usunięcie profilu wymaga potwierdzenia.
- T-SPEECH-1: brak mikrofonu → `NoMicrophone` → tryb tekstowy.
- T-SPEECH-2: cisza → brak wysłania pustej tury.
- T-SPEECH-3 (live): STT plik WAV fixture → transkrypcja WER < 15%.
- T-SPEECH-4: UI nigdy nie twierdzi, że wymowa jest poprawna na podstawie transkrypcji.

## 6. Benchmark modeli (`bench/`)
Zestaw stały, wersjonowany (`bench/cases/{en,it}/*.yaml`), ~40 przypadków na język:
| Kryterium | Metoda | Miara |
|---|---|---|
| Poprawność gramatyczna własnych odpowiedzi | 20 odpowiedzi rozmowy → ocena przez człowieka + LanguageTool | błędy/100 słów |
| Jakość korekty | 30 zdań z oznaczonymi błędami (złoty standard) | precision/recall wykrycia, poprawność kategorii |
| Rozpoznawanie poprawnych wariantów | 15 zdań poprawnych w nietypowej formie | false positive rate (cel < 10%) |
| Jakość wyjaśnień (PL) | 10 wyjaśnień, ocena 1–5 rubryką przez człowieka | średnia |
| Dopasowanie trudności | generuj zadania A2/B1/B2 → klasyfikacja ślepa przez człowieka | trafność poziomu |
| Jakość ćwiczeń | 20 zadań: jednoznaczność klucza, poprawność | % poprawnych |
| Strukturalny JSON | 50 wywołań | % walidnych bez retry |
| EN i IT | te same kryteria, zestaw IT | jak wyżej |
| Opóźnienie | time-to-first-token, całość | p50/p95 ms |
| Zasoby | `nvidia-smi`, RSS procesu Ollama | szczyt VRAM/RAM |
| Tokeny i koszt | `usage` providera × cennik z config | tokeny/sesję 30 min, USD/miesiąc przy 30 min/dzień |
Wynik: `docs/ai-work/BENCHMARK.md` + rekomendacja modelu per rola. Ocena ludzka obowiązkowa dla korekt i wyjaśnień — nie używać tylko LLM-as-judge.

## 7. Bezpieczeństwo
- `/security-review` po F5 i F9; skan `claude-security` przed udostępnieniem innym.
- Sprawdzenie: brak sekretów w git (`git log -p | grep -i key`), uprawnienia `.env` 600, DB 600.
