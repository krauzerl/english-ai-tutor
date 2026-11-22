# REQUIREMENTS

Priorytety: **MVP** = pierwsze użyteczne wydanie; **P2** = po MVP; **P3** = później.
Identyfikatory używane w IMPLEMENTATION_PLAN i TEST_PLAN.

## 1. Zasady nadrzędne
- RQ-0.1 MVP: Silnik dydaktyczny (wybór zadań, ocena, mastery, SRS, profil) działa bez LLM i jest deterministyczny. LLM: generuje treść, prowadzi rozmowę, ocenia odpowiedzi otwarte wg rubryki.
- RQ-0.2 MVP: SQLite = jedyne źródło prawdy o uczniu. Wymiana modelu nie zmienia danych.
- RQ-0.3 MVP: Dane domyślnie lokalne. Wysłanie do zewnętrznego API tylko po zgodzie per profil.
- RQ-0.4 MVP: Każda odpowiedź strukturalna LLM walidowana schematem (pydantic) przed zapisem. Nieprawidłowa → 1 retry → odrzucenie, bez zapisu.
- RQ-0.5: Bez RAG, bazy wektorowej, frameworków agentowych. Ponowna ocena tylko z dowodem potrzeby (np. >10k elementów słownictwa nieobsługiwanych przez SQL).

## 2. Profile i języki
- RQ-1.1 MVP: Wiele profili lokalnych; każdy rekord w DB ma `profile_id`; wszystkie zapytania filtrują po nim (warstwa repozytorium).
- RQ-1.2 MVP: Wybór profilu przy starcie. Opcjonalny PIN (P2) — to nie jest zabezpieczenie przed właścicielem komputera; udokumentować.
- RQ-1.3 MVP: Eksport danych profilu do JSON; usunięcie profilu z kaskadowym usunięciem wszystkich danych + audio.
- RQ-1.4 MVP: Cele konfigurowalne: ogólny / zawodowy / techniczny (IT) / rekrutacja / podróże; docelowy poziom; minuty dziennie.
- RQ-1.5 MVP: Język docelowy = parametr (`target_lang`) w profilu i każdym elemencie treści; pierwszy `en`. P2: `it` bez zmian rdzenia — tylko pakiet treści + prompty + głos Piper.
- RQ-1.6 MVP: Język interfejsu i wyjaśnień: polski (konfigurowalny, P2 inne).

## 3. Diagnoza
- RQ-2.1 MVP: Brak założonego poziomu startowego. Test adaptacyjny (staircase) startuje od A2 i przesuwa się po poprawności.
- RQ-2.2 MVP: Osobne wyniki: grammar, vocabulary, reading, listening, writing. Speaking: MVP — płynność/zakres/poprawność z transkrypcji + zastrzeżenie; wymowa P3.
- RQ-2.3 MVP: Każdy wynik: poziom CEFR, przedział wiarygodności 80% (np. „B1, prawdopodobnie A2+–B1+”), liczba zadań, uzasadnienie (które deskryptory zaliczone/niezaliczone). Bank MVP kończy się na C1: wynik powyżej to „C1 lub wyżej” (sufit), nigdy „C2”; poniżej A1 – „A1 lub niżej”. C2 dopiero po ≥15 zadaniach C2 `human_reviewed` na obszar (04_PEDAGOGY_SPEC §4.3).
- RQ-2.8 MVP: Testy na symulowanych uczniach dowodzą tylko spójności algorytmu, nie trafności CEFR. UI: „szacunek diagnostyczny, trafność niezweryfikowana”.
- RQ-2.4 MVP: Komunikat: wynik diagnostyczny, nie certyfikat.
- RQ-2.5 MVP: Długość testu ≤ 25 min; możliwość przerwania i wznowienia.
- RQ-2.6 MVP: Ponowny test co 30 dni lub na żądanie; mini-weryfikacja umiejętności w zwykłych lekcjach aktualizuje profil (z mniejszą wagą).
- RQ-2.7 MVP: Zadania zamknięte z banku zatwierdzonego (deterministyczna ocena). Otwarte (writing/speaking) oceniane przez LLM wg rubryki opartej o deskryptory CEFR Companion Volume (2020), zapisywane z cytatem dowodu.

## 4. Model dydaktyczny
- RQ-3.1 MVP: Katalog umiejętności (`skills`): id, język, kategoria, poziom CEFR, deskryptor „can-do”, prerekwizyty. Źródło: własna parafraza deskryptorów CEFR + typowe listy gramatyczne (bez kopiowania materiałów chronionych, np. English Profile/EVP — tylko odwołanie do poziomów).
- RQ-3.2 MVP: Mastery per umiejętność: BKT ze stałymi parametrami per źródło dowodu (04_PEDAGOGY_SPEC §4.6). Opanowane: p ≥ 0.85 i poprawne próby produkcyjne w ≥ 2 różnych dniach. Statusy: new → learning → mastered → retained_7d → retained_30d.
- RQ-3.3 MVP: SRS: FSRS (biblioteka `fsrs`) dla słownictwa, konstrukcji i umiejętności opanowanych.
- RQ-3.4 MVP: Active recall: ćwiczenia produkcyjne (uzupełnij, przetłumacz PL→EN, przekształć) zamiast wyłącznie rozpoznawania.
- RQ-3.5 MVP: Rejestr błędów: kategoria (taksonomia stała, np. `tense.present_perfect`, `article.missing`, `preposition`, `word_choice`, `word_order`, `spelling`), przykład, korekta, licznik, ostatnie wystąpienie, powiązana umiejętność. ≥3 wystąpienia → automatyczne zadanie naprawcze.
- RQ-3.6 MVP: Zastosowanie w rozmowie: plan lekcji przekazuje do rozmowy 1–3 konstrukcje „target”; detektor (LLM z walidacją + regex gdy możliwe) rejestruje użycie poprawne/błędne.
- RQ-3.7 MVP: Weryfikacja trwałości: umiejętność opanowana wraca w teście opóźnionym po 7 i 30 dniach (3 niewidziane zadania, ≥1 produkcyjne, zaliczenie ≥2/3); porażka → status learning, p ≤ 0.6.
- RQ-3.8 MVP: Cykl lekcji: diagnoza → wyjaśnienie → ćwiczenie → zastosowanie w rozmowie → utrwalenie → ponowna weryfikacja.
- RQ-3.9 MVP: Planer sesji: 15/30/45/60 min; proporcje wg tabeli w ARCHITECTURE §5.
- RQ-3.11 MVP: Ocena każdej wypowiedzi w 5 wymiarach (gramatyka, słownictwo, naturalność, komunikatywność, płynność) wg rubryk 04_PEDAGOGY_SPEC §2. LLM zwraca tylko obserwacje z dosłownym cytatem; oceny 0–4 liczy kod; za mało dowodów → „za mało danych”. Rozróżnienie: błąd ucznia / wariant poprawny / podejrzenie błędu STT / wypełniacz. Wypełniacze, zawahania i powtórzenia nie są błędami. Każda ocena prowadzi do działania (§2.9).
- RQ-3.12 MVP: Raport sesji (postępy, top-3 błędy z cytatami, mocne strony, ćwiczenia, plan) budowany deterministycznie z DB; narracja LLM opcjonalna i odrzucana, gdy zawiera liczbę spoza danych.
- RQ-3.13 MVP: Statusy treści: draft / ai_checked / human_reviewed / rejected / suspect. Treść AI nigdy nie dostaje human_reviewed bez przeglądu przez CLI `content review`. Diagnoza i testy trwałości tylko z human_reviewed.
- RQ-3.10 MVP: Akceptacja wariantów poprawnych (BrE/AmE, kontrakcje, synonimy) — zadania zamknięte mają listę akceptowanych odpowiedzi; otwarte — LLM musi rozróżnić „błąd” od „inny poprawny wariant” (kategoria `acceptable_variant`, bez kary).

## 5. Funkcje
| ID | Funkcja | Prio |
|---|---|---|
| RQ-4.1 | Konwersacja tekstowa (swobodna i z celami) | MVP |
| RQ-4.2 | Konwersacja głosowa: push-to-talk → STT → LLM → TTS | MVP |
| RQ-4.3 | Lekcje gramatyki: wyjaśnienie (PL) + przykłady + ćwiczenia | MVP |
| RQ-4.4 | Ćwiczenia z braków (z rejestru błędów i mastery) | MVP |
| RQ-4.5 | Słownictwo i konstrukcje + powtórki FSRS | MVP |
| RQ-4.6 | Symulacje sytuacji (scenariusze z rolą, celem, kryteriami sukcesu) | MVP: 5 scenariuszy; P2: więcej |
| RQ-4.7 | Angielski zawodowy/techniczny/rekrutacja (scenariusze + słownictwo) | MVP: rozmowa rekrutacyjna IT; P2: reszta |
| RQ-4.8 | Testy opanowania materiału | MVP |
| RQ-4.9 | Raporty postępów (tydzień, umiejętności, błędy, czas) | MVP: dashboard; P2: eksport PDF |
| RQ-4.10 | Trzy tryby korekty: swobodna rozmowa (podsumowanie), rozmowa z korektą (okresowy recast), intensywna nauka (drabina podpowiedzi, wyjaśnienie, ćwiczenia) — per profil, nadpisywalne per sesja (04_PEDAGOGY_SPEC §3) | MVP |
| RQ-4.11 | Czytanie i słuchanie (teksty + TTS jako nagranie) | MVP: w diagnozie i lekcjach |
| RQ-4.12 | Ocena wymowy (fonemy, akcent) | P3 — wymaga modelu wymowy (np. wav2vec2 phoneme + GOP); poprawna transkrypcja Whisper **nie** oznacza poprawnej wymowy |
| RQ-4.13 | Włoski | P2 |

## 6. Pamięć i kontekst
- RQ-5.1 MVP: Przechowywane: profil kompetencji, cele, wyniki diagnozy, lekcje, podsumowania sesji, błędy+częstość, mastery, słownictwo, terminy FSRS, wyniki ćwiczeń, plan następnej lekcji, zużycie modeli.
- RQ-5.2 MVP: Po sesji: podsumowanie hierarchiczne JSON (sesja → tydzień rolling, P2 → miesiąc), ≤ 300 tokenów sesyjne.
- RQ-5.3 MVP: Kontekst do LLM budowany z: profil skrócony, ostatnie podsumowanie, top-5 aktywnych błędów, cele lekcji, ostatnie N tur rozmowy. Twardy budżet (domyślnie 3000 tokenów wejścia poza bieżącą rozmową).
- RQ-5.4 MVP: Checkpoint co 10 tur lub 5 min: skrót rozmowy zapisany do DB; starsze tury usuwane z kontekstu.
- RQ-5.5 MVP: Pełny transkrypt zapisywany lokalnie (dla użytkownika), ale nigdy nie wysyłany w całości.

## 7. Modele
- RQ-6.1 MVP: Interfejs `LLMProvider` (chat, structured JSON, stream). Implementacje: Ollama, Gemini.
- RQ-6.2 MVP: Wybór modelu per rola: `conversation`, `evaluation`, `generation`. Konfigurowalne w UI.
- RQ-6.3 MVP: Fallback: błąd/timeout Gemini → Ollama (jeśli dostępna) z komunikatem.
- RQ-6.4 MVP: Licznik tokenów i kosztów per wywołanie; limity dzienne/miesięczne; ostrzeżenie przy 80%; blokada przy 100%.
- RQ-6.5 MVP: Benchmark (CLI) — kryteria w TEST_PLAN §6.
- RQ-6.6 MVP: STT: faster-whisper `small.en` (CPU int8). TTS: Kokoro domyślnie, głosy `bf_emma` (domyślny) i `am_michael`; Piper jako alternatywa. LLM domyślny: Bielik 11B (conversation + evaluation, ten sam model).

## 8. UI
- RQ-7.1 MVP: PySide6, widoki: Dashboard, Dzisiejsza lekcja, Konwersacja, Gramatyka, Słownictwo i powtórki, Historia sesji, Profil kompetencji, Ustawienia (modele, prywatność, profil).
- RQ-7.2 MVP: Bez awatarów, maskotek, animacji ozdobnych, punktów/odznak. Dozwolone: licznik dni nauki (wyłączalny), postęp liczbowy.
- RQ-7.3 MVP: Klawiatura: Enter wyślij, Spacja (przytrzymaj) push-to-talk w widoku konwersacji, skróty do widoków.
- RQ-7.4 MVP: Długie operacje (LLM, STT) w wątku roboczym; UI nigdy nie zamarza; widoczny stan i możliwość anulowania.
- RQ-7.5 MVP: Tryb ciemny/jasny wg systemu; kontrast WCAG AA; skalowanie czcionki.

## 9. Bezpieczeństwo i niezawodność
- RQ-8.1 MVP: Klucze API w `~/.config/english-ai-tutor/.env` lub keyring (`keyring`), nigdy w repo/DB. `.env` w `.gitignore` (jest).
- RQ-8.2 MVP: Zgoda na zewnętrzne API: per profil, z datą, odwoływalna; bez zgody provider zewnętrzny niedostępny.
- RQ-8.3 MVP: Awaria modelu: komunikat + retry + fallback; nie tracić tury użytkownika.
- RQ-8.4 MVP: Awaria mikrofonu: wykrycie braku urządzenia/ciszy; przejście na tekst.
- RQ-8.5 MVP: Brak sieci: Gemini wyłączony, Ollama działa.
- RQ-8.6 MVP: DB: WAL, migracje wersjonowane, backup przed migracją.
- RQ-8.7 MVP: Nagrania audio domyślnie nie zapisywane (opcja).
- RQ-8.8 MVP: Logi bez treści rozmów i kluczy (poziom INFO).

## 10. Poza zakresem
Konta w chmurze, synchronizacja, aplikacja mobilna, płatności, certyfikacja, avatary wideo.
