# Moduł 04 – Specyfikacja silnika dydaktycznego

Gałąź `feat/pedagogy-design` (z `113f84e`). Dokument projektowy: **nic z tego nie jest jeszcze zaimplementowane**. Wdrożenie: F3 (treść) i F4 (rdzeń) wg §12–§13 oraz `F3_F4_SONNET_BRIEF.md`; integracja z rozmową w F5.

Zasada nadrzędna (bez zmian, HANDOFF decyzja 1): `tutor/pedagogy/` jest czysty i deterministyczny. LLM **obserwuje i etykietuje** (cytat, kategoria, poprawka, pewność). Kod **waliduje, liczy i decyduje** (oceny, mastery, plan, raport). Żadna liczba pokazywana uczniowi nie pochodzi bezpośrednio z LLM.

## 0. Ustalenia po testach głosowych (moduł 03)
| Temat | Decyzja |
|---|---|
| TTS | Kokoro domyślny (już w `tutor/voice/cli.py`). Głosy do wyboru: `bf_emma` (BrE, domyślny), `am_michael` (AmE). Piper zostaje jako alternatywa za tym samym interfejsem. |
| LLM | Bielik 11B v2.3 Q4_K_M domyślny dla ról `conversation` i `evaluation` (ten sam model = brak przeładowania w 8 GiB VRAM). |
| STT | Whisper `small.en`, CPU int8. |
| Gemini | Odroczony. Nic w F3/F4 od niego nie zależy. |
| Audio | Transkrypcje zapisywane (`turn.text`), nagrania nigdy. Metadane czasowe słów (§2.6) to nie nagranie; zapisywane tylko jako zagregowane metryki. |
| Odmiana | BrE i AmE równorzędnie poprawne (§2.4). Mieszanie odmian w mowie nie jest błędem. |
| Moduł głosowy | Bez przebudowy. Jedyna zmiana w F5: **dodatkowa** metoda `WhisperSTT.transcribe_detailed()` (§2.6); `transcribe()` bez zmian. |

## 1. Przepływ jednej wypowiedzi
```
uczeń (tekst | głos→STT)
  │
  ├─► rozmowa: Bielik stream → TTS            (ścieżka krytyczna, nic jej nie blokuje poza trybem intensywnym)
  │
  └─► kolejka oceny (app/, 1 wątek, nigdy równolegle z generowaniem rozmowy)
        1. prefiltr deterministyczny  (pedagogy/assessment.py: wypełniacze, powtórzenia, autonaprawy)
        2. TurnEval LLM               (rola evaluation, JSON wg schematu, ≤120 tokenów wyjścia)
        3. walidatory deterministyczne (cytat istnieje, taksonomia, warianty, sygnały STT)
        4. zapis `observation`          (także odrzucone, z powodem)
        5. polityka korekty            (pedagogy/correction.py: co, kiedy i jak pokazać)
        6. aktualizacje                (error_log, BKT, karty FSRS)
```
Kroki 1 i 3–6 są czystymi funkcjami w `pedagogy/`. Krok 2 i kolejka leżą w `app/` (F5).

## 2. Ocena wypowiedzi

### 2.1 Pięć wymiarów
| Wymiar | Co obserwuje | Źródło dowodu | Kto liczy wynik |
|---|---|---|---|
| Gramatyka (G) | błędy form i struktur; zakres struktur użytych poprawnie | cytaty LLM (`span`→`fix`, kategoria) | kod: ważona liczba błędów /100 słów + zakres |
| Słownictwo (V) | zły dobór słowa, kolokacje, brak słowa (obejście, przejście na PL) | cytaty LLM | kod: jw. + liczba różnych lematów ≥ poziomu lekcji (lista w `content/`) |
| Naturalność (N) | poprawne, ale nieidiomatyczne: kalki z PL, rejestr, kolokacje | cytaty LLM z propozycją „bardziej naturalnie” | kod: liczba obserwacji /100 słów |
| Komunikatywność (C) | czy wypowiedź realizuje intencję wobec pytania tutora / celu scenariusza | etykieta LLM `ok/partial/fail/na` + cytat; kryteria sukcesu scenariusza | kod: odsetek `ok` wśród wypowiedzi ocenialnych |
| Płynność (F) | tempo, pauzy, długość ciągów bez pauz, autonaprawy | **tylko głos**: znaczniki czasu słów Whispera (§2.6) | kod: metryki liczbowe; ocena względem własnej linii bazowej ucznia |

Wymowa: **nie jest oceniana** (RQ-4.12, P3). Żaden komunikat nie może sugerować, że poprawna transkrypcja oznacza poprawną wymowę. Tekst wpisany: F = „nie dotyczy”.

### 2.2 Skala i rubryki (ocena sesji, nie pojedynczego zdania)
Pojedyncza wypowiedź daje **obserwacje**, nie ocenę. Ocena 0–4 jest liczona dla wymiaru w sesji (lub w oknie ≥ minimalnej ilości dowodów). Skala dotyczy wykonania względem poziomu lekcji. **To nie jest poziom CEFR** i nie zmienia `competence` (§4.6).

Wartości progów są początkowe, `content/<lang>/rubric.yaml`, kalibrowane po F8.

| Ocena | G / V (ważone błędy na 100 słów, wagi sev 1/2/3 = 0,5/1/2) | N | C (`ok` / ocenialne) | F (vs mediana ucznia z 3 ostatnich sesji) |
|---|---|---|---|---|
| 4 | ≤ 1, i ≥ 2 struktury/słowa z poziomu lekcji użyte poprawnie | ≤ 1 | ≥ 90% | tempo ≥ +10% i długie pauzy ≤ −20% |
| 3 | ≤ 3 | ≤ 3 | ≥ 75% | w granicach ±10% |
| 2 | ≤ 6 | ≤ 6 | ≥ 50% | tempo −10…−25% lub długie pauzy +20…+50% |
| 1 | ≤ 10 | > 6 | ≥ 25% | gorzej niż poziom 2 |
| 0 | > 10 | — | < 25% | — |

Opisy słowne każdej oceny (PL, dla raportu) w `rubric.yaml`, np. G3: „Błędy pojawiają się, ale nie zaburzają sensu; większość struktur z lekcji poprawna”.

**Wymagane dowody** (inaczej wynik = `insufficient_evidence`, bez liczby):
- G, V, N: ≥ 50 słów ucznia w ≥ 5 wypowiedziach ocenialnych.
- C: ≥ 5 wypowiedzi z etykietą różną od `na`.
- F: ≥ 60 s mowy ucznia w ≥ 5 wypowiedziach głosowych; ocena względem bazy dopiero od 3. sesji głosowej (wcześniej tylko metryki surowe, bez oceny).
- Każda ocena < 4 w G/V/N ma w raporcie ≥ 1 cytat-dowód. Ocena bez cytatu jest błędem walidacji raportu.

### 2.3 Rodzaje obserwacji i rozróżnienia
Każda obserwacja ma `kind`:

| kind | Znaczenie | Wpływ na ucznia |
|---|---|---|
| `error` | rzeczywisty błąd ucznia | liczony w G/V, `error_log`, BKT, może wywołać korektę |
| `variant` | poprawna forma, inna niż „podręcznikowa” (BrE/AmE, kontrakcja, synonim, szyk dopuszczalny) | brak kary; nie jest pokazywany jako błąd (opcjonalnie jako informacja w trybie intensywnym) |
| `natural` | poprawne, ale brzmi nienaturalnie | wymiar N; sugestia, nigdy „błąd”; nie obniża BKT, chyba że kolokacja jest celem lekcji |
| `stt_suspect` | możliwy błąd rozpoznawania mowy | **nigdy** liczony ani pokazywany jako błąd ucznia (§2.5) |
| `disfluency` | wypełniacz, zawahanie, powtórzenie, fałszywy start | nie jest błędem; zasila tylko metryki F |

Kolejność decyzji (deterministyczna, `assessment.classify()`), pierwsza pasująca reguła wygrywa:
1. `span` nie występuje dosłownie (po normalizacji wielkości liter i białych znaków) w wypowiedzi → **odrzuć** (`drop_reason=span_not_found`).
2. `span` leży w całości w fragmencie oznaczonym przez prefiltr jako wypełniacz/powtórzenie/porzucony fałszywy start → `disfluency`.
3. Para (`span`, `fix`) pasuje do `content/<lang>/variants.yaml` → `variant`.
4. Wejście głosowe i kategoria ∈ {`spelling`, `punctuation`, `capitalization`} → **odrzuć** (w mowie nie istnieją).
5. Wejście głosowe i (słowo w `span` ma prawdopodobieństwo Whispera < 0,5 **lub** para należy do listy par wrażliwych na STT, §2.5) → `stt_suspect`.
6. Kategoria spoza taksonomii, `fix == span`, `fix` dłuższy niż 3× `span` + 20 znaków → **odrzuć**.
7. W przeciwnym razie `kind` z LLM (`error` lub `natural`).

Odrzucone obserwacje zapisujemy (`status=dropped`) — to metryka jakości oceniającego modelu (F8, regresja).

### 2.4 Warianty poprawne
`content/en/variants.yaml` — lista par i reguł, np.:
- pisownia: colour/color, organise/organize, travelled/traveled, programme/program (poza IT), licence(n.)/license;
- słownictwo: flat/apartment, holiday/vacation, lift/elevator, CV/résumé;
- gramatyka: have got/have, gotten/got, „in hospital”/„in the hospital”, „the team are/is”, past simple z just/already/yet (AmE) vs present perfect;
- kontrakcje i formy pełne; „whom”/„who” w mowie potocznej.
Zadania zamknięte mają listę `answers` z wariantami (RQ-3.10). Walidator treści sprawdza, że jeśli klucz zawiera słowo z `variants.yaml`, wariant też jest akceptowany.

### 2.5 Podejrzenie błędu STT
Sygnały (dostępne po dodaniu `transcribe_detailed()`):
- prawdopodobieństwo słowa < 0,5 w `span`;
- pary wrażliwe (lista w `content/en/stt_confusables.yaml`): brak/wstawienie `a/the/an`, końcówki `-s/-ed`, `'ll/'d/'ve`, `can/can't`, `to/too/two`, `there/their/they're`, `your/you're`, `its/it's`, nazwy własne;
- `span` obejmuje pierwsze lub ostatnie słowo wypowiedzi (urwanie przez endpointer).

Postępowanie: `stt_suspect` nie trafia do `error_log` ani BKT. Gdy w jednej kategorii zbierze się ≥ 3 podejrzeń w ciągu 14 dni, planer dodaje **zadanie pisemne lub zamknięte** z tej kategorii — zamienia niepewność w dowód deterministyczny. W trybie intensywnym tutor może zapytać neutralnie („Did you say *went* or *go*?”), nigdy „źle wymówiłeś”.

### 2.6 Płynność ze znaczników czasu
F5 dodaje `WhisperSTT.transcribe_detailed(audio) -> Transcript(text, words[(word, start, end, prob)])` (faster-whisper ma `word_timestamps=True`; koszt mierzyć — jeśli > +15% czasu STT, liczyć tylko w trybach z korektą). Metryki (`pedagogy/fluency.py`, czysta funkcja):
- tempo artykulacji: słowa / (czas mowy − pauzy ≥ 250 ms) [sł/min];
- długie pauzy wewnątrz wypowiedzi: liczba ≥ 1,0 s na minutę;
- średnia długość ciągu (MLR): słowa między pauzami ≥ 400 ms;
- autonaprawy: z prefiltra (powtórzenie z modyfikacją, fałszywy start).
Ograniczenie zapisane w raporcie: Whisper często pomija „um/uh”, więc liczba wypełniaczy jest tylko informacyjna i nie wchodzi do oceny. Normy absolutne sł/min dla CEFR nie są walidowane — dlatego ocena F jest względna do linii bazowej ucznia.

### 2.7 Wypełniacze, zawahania, powtórzenia
Prefiltr (`assessment.prefilter()`, lista w `content/en/disfluency.yaml`): wypełniacze (`um, uh, er, erm, hmm, you know, I mean` w pozycji wtrącenia), powtórzenia tokenów (`I I think`, `the the`), fałszywe starty i autonaprawy (`I goed— I went`). Oceniana jest **forma końcowa po naprawie**. Udana autonaprawa (zła forma → poprawna w tej samej wypowiedzi) to dowód pozytywny dla umiejętności (BKT: obserwacja poprawna z `hint_level=0`), nie błąd. Prefiltr nie usuwa tekstu z `turn.text`; tylko oznacza zakresy przekazywane do TurnEval jako `[[F:...]]`.

### 2.8 Pewność i niepewność
- LLM zwraca pewność kategorialnie `h/m/l` (liczby z LLM są niestabilne). Obserwacje `l` nie wchodzą do `error_log` ani BKT; są widoczne tylko w analizie wrażliwości.
- Niepewność oceny wymiaru = **analiza wrażliwości**: ocena liczona (a) z obserwacjami `h+m`, (b) z `h+m+l` i z `stt_suspect` traktowanymi jako błędy. Gdy (a) ≠ (b), raport pokazuje przedział („2–3, niepewne”), inaczej jedną liczbę.
- Mała liczba dowodów → `insufficient_evidence` (§2.2), nie ocena.
- Kalibracja pewności modelu: w F8 na złotym zbiorze sprawdzamy precyzję per poziom pewności. Jeśli precyzja `m` < 0,8, `m` traktujemy jak `l` (przełącznik w `rubric.yaml`).

### 2.9 Każda ocena → działanie dydaktyczne
| Obserwacja / wynik | Działanie (deterministyczne) |
|---|---|
| `error` sev ≥ 2 lub kategoria z `error_log.count ≥ 3` lub konstrukcja celu lekcji | kandydat do korekty (§3) + `error_log` + BKT(niepoprawna) |
| `error` sev 1, pierwsze wystąpienie | tylko `error_log`; w raporcie, jeśli w top-3 |
| `error_log` ≥ 3 wystąpienia w ≥ 2 wypowiedziach (30 dni) | zadanie naprawcze w następnym planie (priorytet 2 planera) |
| `natural` | sugestia „bardziej naturalnie: …” + karta FSRS `construction` (jeśli fraza z listy treści lub zaakceptowana przez ucznia) |
| `variant` | brak; opcjonalnie notka „też poprawne (BrE/AmE)” w trybie intensywnym |
| `stt_suspect` ≥ 3 w kategorii / 14 dni | zadanie pisemne z kategorii |
| C = `fail` | w rozmowie: prośba o doprecyzowanie (naturalna); ≥ 2 w scenariuszu → powtórka scenariusza z podpowiedzią frazową |
| konstrukcja celu użyta poprawnie | BKT(poprawna), karta FSRS `construction` Good |
| G/V ocena ≤ 1 | następna lekcja na poziomie θ−0,5 (planer) + powtórka prerekwizytów |
| F spadek ≥ 2 sesje | ćwiczenie płynności (powtórzenie opowieści 4/3/2 min, odpowiedzi z limitem czasu) |
| `insufficient_evidence` | planer wydłuża część rozmowy w następnej sesji o 2 min |

## 3. Mechanizm korekty

### 3.1 Trzy tryby (`profile.correction_style`, nadpisywalne per sesja)
| | `summary` – swobodna rozmowa | `periodic` – rozmowa z korektą | `intensive` – intensywna nauka |
|---|---|---|---|
| Ocena LLM | partiami: co 5 wypowiedzi lub przy checkpoincie / końcu sesji | po każdej odpowiedzi tutora, w tle | po każdej wypowiedzi, **przed** odpowiedzią tutora |
| Przerywanie rozmowy | nigdy | max 1 korekta na 3 tury ucznia | każdy istotny błąd (sev ≥ 2) i każdy błąd w konstrukcji celu |
| Forma korekty | raport końcowy + quiz autokorekty (3–5 zdań ucznia: „znajdź i popraw błąd”) | **recast** w następnej odpowiedzi tutora (przeformułowanie poprawną formą bez przerywania) + zwijana linia pod wiadomością | drabina podpowiedzi (§3.2) + wyjaśnienie PL + 1–2 mini-ćwiczenia |
| Co korygować | top-5 wg priorytetu | sev ≥ 2 lub nawracające lub cel lekcji; nie więcej niż 1 kategoria naraz | jw. + sev 1 w konstrukcji celu |
| Dodatkowe opóźnienie tury | 0 | 0 (ocena w czasie, gdy uczeń mówi/myśli) | ocena: cel ≤ 6 s p50, twardy limit 10 s (przekroczenie → tura bez korekty, nic nie zmyślamy) |

Migracja istniejącej wartości: `immediate` → `periodic`, `summary` → `summary`.

Priorytet korekty (`correction.priority()`): `sev × (1 + log2(count_30d)) × (2 jeśli cel lekcji) × (0,5 jeśli kategoria była korygowana w tej sesji)`. Remis → nowsza wypowiedź.

### 3.2 Drabina podpowiedzi (tryb intensywny; w `periodic` tylko krok 0 = recast)
Stan per błąd w `correction.py` (maszyna stanów, czysta):
1. **L1 sygnał** – „Almost! Check the verb.” (bez poprawki; zachęta do autokorekty).
2. **L2 podpowiedź metajęzykowa (PL)** – szablon z `errors.yaml`: „Mówisz o zakończonej przeszłości — jaki czas?”.
3. **L3 elicytacja** – „I ___ (go) there yesterday.” albo wybór z 2 opcji.
4. **L4 jawna poprawka** – poprawna forma + wyjaśnienie PL (szablon z `errors.yaml`; LLM tylko gdy szablonu brak) + 1–2 mini-ćwiczenia z banku (umiejętność powiązana z kategorią).

Po każdym kroku uczeń próbuje ponownie. Sprawdzenie próby: deterministycznie (znormalizowana próba zawiera `fix` lub pasuje do wzorca umiejętności); jeśli niejednoznaczne — jedno krótkie wywołanie TurnEval tylko dla tej próby. Wynik zapisuje `attempt(source=correction, hint_level=1..4, correct)`. FSRS/BKT: poprawnie po L1 = dowód prawie pełny (Good), po L2–L3 = Hard, po L4 lub brak = Again.

**Ponowne użycie (uptake):** poprawiona konstrukcja trafia do `session.plan_json.reuse_targets`. Prompt rozmowy dostaje instrukcję stworzenia okazji do jej użycia w ciągu 2–5 tur (np. pytanie wymagające czasu przeszłego). Poprawne użycie bez podpowiedzi = najsilniejszy dowód (BKT poprawna, `hint_level=0`). W `summary` ponowne użycie następuje w quizie autokorekty i w następnej lekcji.

### 3.3 Opóźnienia i ograniczenia Bielika 11B
Fakty (02/03): ~11 tok/s generacji z offloadem CPU, 8 GiB VRAM, Ollama obsługuje żądania sekwencyjnie.
- Ta sama nazwa modelu dla `conversation` i `evaluation` (bez przeładowania). Inny model dla `evaluation` → ostrzeżenie w logu i w ustawieniach.
- Schemat TurnEval zwięzły (krótkie klucze, bez wyjaśnień), `max_tokens` 160; wypowiedź bez błędów ≈ 15 tokenów wyjścia. Wyjaśnienia PL pochodzą z szablonów, nie z oceny.
- Stały prefiks promptu oceny (instrukcja + skrócona taksonomia) przed zmienną częścią — Ollama ponownie używa cache prefiksu.
- Kolejka oceny w `app/`: zadanie startuje dopiero po zakończeniu strumienia rozmowy; nowa tura ucznia **przerywa** trwającą ocenę (zamknięcie połączenia, jak `VoiceTutor.cancel()`), a niedokończone wypowiedzi wracają do kolejki i są oceniane partią później. Rozmowa ma zawsze priorytet.
- Partia: do 5 wypowiedzi w jednym wywołaniu (`u: [...]` z indeksami); wyjście rośnie tylko z liczbą błędów.
- Kontekst oceny: wypowiedź ucznia + poprzednia wypowiedź tutora (do C) + cele lekcji; bez historii sesji (≤ ~700 tokenów wejścia).
- Ryzyko jakości: Bielik jest modelem polskocentrycznym; jakość wykrywania błędów EN jest **niezmierzona**. Zasada: precyzja ponad czułość — prompt każe pomijać niepewne. Brama przed włączeniem `periodic`/`intensive` jako domyślnych: F8 na złotym zbiorze — precyzja `error` ≥ 0,80, fałszywe alarmy na zdaniach poprawnych < 10%. Niespełnione → domyślnie `summary`, a korekty formułowane jako „sugestia”.
- Wszystkie opóźnienia powyżej to szacunki; pomiar p50/p95 obowiązkowy w F5 (live).

### 3.4 Schemat TurnEval (wyjście LLM, walidowane pydantic w `pedagogy/schemas.py`)
```json
{"u":[{"i":0,
       "o":[{"s":"I go there","f":"I went there","k":"error","c":"tense.past_simple","v":2,"p":"h"}],
       "t":[{"id":"en.gram.past_simple","r":"bad","s":"I go there"}],
       "cm":"ok"}]}
```
`s` span (dosłowny cytat), `f` poprawka, `k` ∈ {error, natural, variant}, `c` kategoria taksonomii, `v` waga 1–3 (1 nie zmienia sensu, 2 wyraźnie zauważalny, 3 utrudnia zrozumienie), `p` ∈ {h,m,l}, `t` użycie konstrukcji celu (`ok/bad`), `cm` ∈ {ok, partial, fail, na}. LLM nie zwraca `stt_suspect` ani `disfluency` — te nadaje kod. Wersja promptu w `observation.prompt_version`.

## 4. Diagnoza i adaptacja

### 4.1 Kompetencje niezależne
Obszary: `grammar`, `vocabulary`, `reading`, `listening` (zadania zamknięte, ocena deterministyczna), `writing`, `speaking` (otwarte, rubryka). Każdy obszar ma własny estymator; wynik jednego nie jest priorem drugiego. (`speaking` z transkrypcji: zakres, poprawność, płynność, interakcja — bez wymowy.)

### 4.2 Estymacja: siatka bayesowska (dopracowanie staircase)
Skala θ ∈ [0,5; 6,5] (A1 = 1 … C2 = 6), siatka co 0,05. Prior N(2,5; 1,5²) obcięty do siatki.
- Trudność zadania: `b = level_index(cefr) + 0,5 · difficulty`, `difficulty ∈ [−1; 1]` nadane przez autora (nieskalibrowane).
- Model odpowiedzi: `P(poprawna | θ) = g + (1 − g) · σ(1,0 · (θ − b))`, `g` = 1/liczba opcji dla zamkniętych wyboru, 0 dla produkcyjnych. Nieskalibrowane trudności ⇒ nachylenie celowo niskie (1,0), co poszerza przedziały zamiast udawać precyzję.
- Wybór zadania: niewykorzystane zadanie obszaru z `b` najbliższym średniej a posteriori (zachowanie schodkowe), z losowym remisem (ziarno w `diagnosis_run.state_json`, deterministyczne w testach).
- Stop: SD a posteriori < 0,35 **lub** 10 zadań w obszarze; minimum 5 zadań; limit całego testu 25 min (RQ-2.5). Przerwanie → stan w `diagnosis_run.state_json`, wznowienie od tego miejsca.
- Wynik: poziom = przedział [k−0,5; k+0,5) zawierający średnią; **przedział wiarygodności 80%** (10.–90. percentyl a posteriori) przetłumaczony na etykiety („B1, prawdopodobnie A2+–B1+”). Zapis: `competence(theta=średnia, se=SD, n_items, rationale)` + percentyle w `rationale` JSON.
- Writing/speaking: rubryka deskryptorów (paraf. CEFR CV 2020) `met/partial/not_met` z cytatem; poziom = najwyższy, dla którego ≥ 70% deskryptorów `met` i wszystkie niższe poziomy spełnione; przedział zawsze co najmniej ±1 poziom (ocena modelowa = wysoka niepewność), znacznik `source=llm_rubric`.

### 4.3 Niespójność A1–C2 vs bank do C1 — rozwiązanie
Bank zadań zamkniętych MVP obejmuje A1–C1. Konsekwencje:
- **Sufit:** jeśli 90. percentyl a posteriori > 5,5 i uczeń poprawnie rozwiązał ≥ 3 z 4 ostatnich zadań C1, wynik to **„C1 lub wyżej”** (`ceiling=true`), nigdy „C2”. Średnia θ obcięta do 5,5 przy zapisie poziomu.
- **Podłoga:** analogicznie „A1 lub niżej” (`floor=true`).
- Skala θ i typ `CEFR` dalej mają C2 (dane i przyszłe treści), ale `report`/UI nie wyświetlają C2 bez zadań C2 `human_reviewed` w danym obszarze (≥ 15). Writing/speaking: C2 też niewydawane w MVP (brak zweryfikowanych deskryptorów i kotwic).
- REQUIREMENTS RQ-2.3 i TEST_PLAN T-PED-3 zaktualizowane odpowiednio.

### 4.4 Trafność: czego symulacje NIE dowodzą
Testy T-PED-1/2 na symulowanych uczniach sprawdzają **tylko** spójność algorytmu (zbieżność, pokrycie przedziałów przy założonym modelu). Nie dowodzą, że wynik odpowiada prawdziwemu CEFR, bo symulacja używa tych samych trudności, co estymator. W UI i raporcie wynik zawsze: „szacunek diagnostyczny, nie certyfikat; trafność niezweryfikowana”. Plan walidacji rzeczywistej (P2, poza F4): opcjonalne pole „wynik zewnętrzny” (certyfikat, ocena nauczyciela, data) w profilu; porównanie dopiero przy ≥ 20 parach; kalibracja trudności (IRT 1PL) dopiero przy ≥ 200 odpowiedziach na zadanie — przy kilku lokalnych profilach może to nigdy nie nastąpić, i to zostaje napisane wprost.

### 4.5 Katalog umiejętności i prerekwizyty
Plik `content/<lang>/skills/<domain>.yaml`, schemat §5.1. Graf prerekwizytów musi być acykliczny (walidator). Umiejętność jest **odblokowana**, gdy każdy prerekwizyt ma status ≥ `mastered` lub poziom obszaru ucznia ≥ poziom prerekwizytu + 1 (zaawansowany uczeń nie musi „zaliczać” A1). Planer wybiera tylko odblokowane.

### 4.6 BKT (mastery)
Stałe parametry per źródło dowodu (`content/<lang>/rubric.yaml` → sekcja `bkt`, wspólne dla języków):

| źródło | p_init | p_learn | p_slip | p_guess |
|---|---|---|---|---|
| zamknięte wybór (MC) | 0,2 | 0,15 | 0,10 | 1/opcje |
| zamknięte produkcyjne (luka, transformacja, PL→EN) | 0,2 | 0,15 | 0,10 | 0,05 |
| rozmowa (`error`/`t` z TurnEval, pewność h/m) | — | 0,10 | 0,15 | 0,10 |
| korekta z podpowiedzią L2–L4 | — | 0,10 | 0,10 | 0,30 |

Aktualizacja standardowa: posterior z obserwacji, potem `p = p_post + (1 − p_post) · p_learn`. p_init z diagnozy: σ(θ_obszaru − b_umiejętności) obcięte do [0,05; 0,6]. Obserwacje `stt_suspect`, `l`, `variant`, `natural` (poza celem) nie aktualizują BKT.

Statusy `skill_state.status`: `new → learning → mastered → retained_7d → retained_30d`.
- `mastered`: p ≥ 0,85 **i** poprawne próby produkcyjne w ≥ 2 różnych dniach (`attempt.day`).
- `retained_7d` / `retained_30d`: §4.8.
- Porażka testu trwałości: status `learning`, `p = min(p, 0,6)`, `mastered_at = NULL`, licznik `relapses += 1`.

Zmiana w kompetencji (CEFR): mini-weryfikacje w lekcjach (zadania z banku `human_reviewed`, pula `practice`) aktualizują posterior obszaru z wagą 0,5 (log-wiarygodność × 0,5). Oceny rubryki z rozmowy (§2.2) **nie** zmieniają CEFR.

### 4.7 FSRS i powtórki
Biblioteka `fsrs`. Typy kart: `vocab` (term), `construction` (fraza/wzorzec), `skill_check` (umiejętność opanowana). Mapowanie oceny:
- błąd lub brak odpowiedzi → Again; poprawnie po podpowiedzi lub częściowo (rubryka `partial`) → Hard; poprawnie → Good; poprawnie w zamkniętym zadaniu w czasie < `fast_ms` (per typ, `rubric.yaml`) → Easy.
Planer: zaległe karty ≤ 30% czasu sesji; kolejność wg `due_at`, potem retrievability rosnąco.

### 4.8 Weryfikacja trwałości 7 i 30 dni
- Przy przejściu do `mastered` planer ustawia `verify_due_at = mastered_at + 7 dni`.
- Test: 3 zadania **niewidziane** podczas nauki tej umiejętności (sprawdzane w `attempt`), z puli `retention`, w tym ≥ 1 produkcyjne; bez podpowiedzi. Zaliczony: ≥ 2/3 poprawne, w tym produkcyjne.
- Zaliczony 7 d → `retained_7d`, `verify_due_at = +30 dni od mastered_at` (okno 30–37 dni) → zaliczony → `retained_30d` („trwałe”).
- Okno przegapione → test w najbliższej sesji; rzeczywiste opóźnienie zapisane (`attempt.feedback_json.delay_days`) i pokazane w raporcie.
- Po `retained_30d` umiejętność dalej żyje w FSRS jako `skill_check`.
- Brak niewidzianych zadań → test odroczony i sygnał „za mało treści” w raporcie dla autora treści (nie udajemy weryfikacji na znanych zadaniach).

### 4.9 Rejestr powtarzających się błędów
`error_log` agreguje per (profil, kategoria, skill_id). Przykłady i poprawki pochodzą z `observation` (link `example_observation_id`). Statusy:
- `active` – ≥ 1 wystąpienie w ostatnich 30 dniach;
- `recurring` – ≥ 3 wystąpienia w ≥ 2 wypowiedziach w 30 dniach → zadanie naprawcze;
- `improving` – po zadaniu naprawczym poprawne użycia ≥ 3, błędne ≤ 1 w ostatnich 3 sesjach z okazją użycia;
- `resolved` – 0 błędów i ≥ 3 poprawne użycia w 3 kolejnych sesjach z okazją (okazja = obserwacja `t` lub zadanie tej kategorii); ponowne wystąpienie → `recurring`, `reopened += 1`.
Taksonomia: rdzeń wspólny (`tense, aspect, agreement, article, determiner, preposition, word_order, word_choice, collocation, morphology, register, spelling, punctuation, capitalization, omission, l1_calque`) + podkategorie per język w `content/<lang>/errors.yaml` (np. `tense.present_perfect`, `article.missing`). Kod zna tylko listę z YAML i rdzeń.

## 5. Materiały dydaktyczne

### 5.1 Katalog umiejętności (`content/<lang>/skills/<domain>.yaml`)
```yaml
- id: en.gram.past_simple           # <lang>.<domain>.<slug>, unikalne, niezmienne
  lang: en
  domain: grammar                    # general | grammar | conversation | tech_it | interview
  area: grammar                      # obszar kompetencji z §4.1
  cefr: A2
  can_do_pl: "Opowiadam o zakończonych zdarzeniach w przeszłości."   # parafraza, nie cytat
  prereqs: [en.gram.to_be_past, en.vocab.time_expressions_basic]
  error_categories: [tense.past_simple, morphology.irregular_past]
  target_patterns: ['\b(went|did|was|were|\w+ed)\b']   # opcjonalne, wspiera detekcję użycia
  explanation_ref: grammar/past_simple.md
  tags: [narration]
```
Domeny i zakres katalogu MVP (≈ 90 umiejętności, F3): grammar A1–C1 (~40), general vocabulary/funkcje językowe (~15), conversation (small talk, prośby, opinie, zgoda/niezgoda, dopytywanie; ~12), tech_it (stand-up, opis błędu, code review, wyjaśnianie architektury, e-mail do klienta; ~12), interview (przedstawienie się, doświadczenie STAR, pytania behawioralne, pytania techniczne, negocjacje; ~10).

### 5.2 Bank zadań (`content/<lang>/items/<area>/<cefr>.yaml`)
```yaml
- id: en.it.gram.past_simple.0007
  lang: en
  skill_ids: [en.gram.past_simple]
  area: grammar
  type: gap                 # mc | gap | transform | translate_pl | reorder | reading_mc | listening_mc | dictation | open_write | open_speak
  cefr: A2
  difficulty: 0.0           # -1..1 w obrębie poziomu
  pools: [diagnosis, practice, retention]   # pula retention rozłączna z practice dla tej samej umiejętności
  domain: tech_it
  prompt: "Yesterday we ___ (deploy) the hotfix to production."
  options: null
  answers: ["deployed"]     # wszystkie akceptowane, z wariantami
  explanation_pl: "Zakończona czynność w przeszłości z 'yesterday' → past simple."
  audio_text: null          # listening: tekst dla TTS (głos wg profilu)
  provenance: {source: ai_generated, model: "bielik-11b-v2.3", prompt_version: gen_item.v1, created_at: 2026-11-30}
  review:
    status: draft           # draft | ai_checked | human_reviewed | rejected | suspect
    reviewer: null          # id z content/reviewers.yaml; wymagany dla human_reviewed
    reviewed_at: null
    notes: null
```
Pole `reviewed: true` z wcześniejszego planu zastąpione przez `review.status`.

### 5.3 Proces weryfikacji materiałów
1. **Generowanie** (skrypt `tools/gen_items.py`, F3; LLM rola `generation`) → zawsze `provenance.source=ai_generated`, `review.status=draft`. Generator nie może zapisać pól `reviewer`/`reviewed_at` ani statusu innego niż `draft` (test).
2. **Kontrole deterministyczne** (walidator): schemat; istniejące `skill_ids`; MC: klucz ∈ opcje, opcje unikalne, dokładnie 1 klucz; luka: dokładnie jedna luka; warianty z `variants.yaml`; długość wg poziomu; brak duplikatów (normalizowany prompt); brak danych osobowych.
3. **Kontrola AI na ślepo**: drugi model/wywołanie rozwiązuje zadanie bez klucza; niezgodność z kluczem albo zgłoszenie „więcej niż jedna poprawna” → `rejected` lub `draft` z notatką. Zgodność → `ai_checked`. **`ai_checked` ≠ zweryfikowane przez człowieka** i UI to rozróżnia.
4. **Przegląd człowieka**: wyłącznie przez interaktywne CLI `python main.py content review` (pokazuje zadanie, klucz, wyjaśnienie; człowiek wybiera akceptuj / popraw / odrzuć). Tylko ta ścieżka ustawia `human_reviewed`, `reviewer` (z `content/reviewers.yaml`) i `reviewed_at`. Treści pisane od zera przez człowieka: `provenance.source=human`, nadal wymagają `human_reviewed` (autor może być recenzentem).
5. **Po wdrożeniu**: statystyki zadań z `attempt`; zadanie z odsetkiem poprawnych < 20% u uczniów z θ ≥ b+1 lub zgłoszone przez ucznia („zgłoś błąd w zadaniu”) → `suspect`, wyłączone z diagnozy do ponownego przeglądu.

Użycie wg statusu: diagnoza, testy trwałości i mini-weryfikacje CEFR → **tylko `human_reviewed`**. Ćwiczenia → `human_reviewed` lub `ai_checked` z widoczną etykietą „materiał niezweryfikowany przez człowieka” (ustawienie profilu `allow_unreviewed_practice`, domyślnie `true`, wyłączalne). `draft`, `rejected`, `suspect` → nigdy.

### 5.4 Pozostała treść
`content/<lang>/`: `errors.yaml` (podkategorie + szablony wyjaśnień PL i podpowiedzi L1–L3), `variants.yaml`, `stt_confusables.yaml`, `disfluency.yaml`, `rubric.yaml` (progi, opisy ocen, parametry BKT/FSRS), `scenarios/*.yaml` (rola, cel, 3–5 kryteriów sukcesu z przykładowymi frazami, konstrukcje celu, poziom), `prompts/*.md` (wersjonowane: `conversation`, `turn_eval`, `rubric_eval`, `report_narrative`, `gen_item`, `solve_item`), `grammar/*.md` (wyjaśnienia PL). Te same zasady statusów (§5.3) dotyczą scenariuszy i wyjaśnień.

### 5.5 Włoski bez przebudowy rdzenia
Dodanie `it` = nowy katalog `content/it/` (skills, items, errors.yaml z podkategoriami np. `agreement.gender`, `article.partitive`, `variants.yaml` pusty lub regionalizmy, `stt_confusables.yaml`, `disfluency.yaml` z `ehm, cioè, allora`), Whisper `small` z `--language it`, głos TTS (Kokoro `if_sara`/`im_nicola` lub Piper `it_IT-*`, do odsłuchu). Kod: brak zmian. Wymuszają to T-ARCH-2 i test `T-LANG-1` (cały zestaw testów pedagogy przechodzi na syntetycznym pakiecie `content/xx/`).

## 6. Raport sesji

### 6.1 Zawartość i źródła (wszystko z DB, deterministycznie, `pedagogy/report.py`)
| Sekcja | Skąd | Reguła |
|---|---|---|
| Rzeczywiste postępy | zmiany `skill_state.status` w sesji, wyniki testów trwałości (z rzeczywistym opóźnieniem), przejścia `error_log` (`recurring→improving→resolved`), nowe karty i powtórki FSRS (liczby) | tylko zdarzenia zapisane; bez „+23%”. Mastery pokazywane jako status, nie surowe p |
| Najważniejsze błędy | top-3 `error` (pewność h/m) wg priorytetu §3.1 | każdy z dosłownym cytatem ucznia, poprawką, kategorią PL i liczbą wystąpień (sesja / 30 dni) |
| Mocne strony | umiejętności / konstrukcje celu użyte poprawnie ≥ 2× bez podpowiedzi; zaliczone testy trwałości; kategorie z ≥ 3 okazjami i 0 błędów; udane autonaprawy | każdy z cytatem; brak dowodu → sekcja pusta z komunikatem „za mało danych”, nie ogólnik |
| Oceny wymiarów | §2.2 | ocena 0–4 lub przedział lub `za mało danych`; F tylko głos; zawsze informacja „wymowa nieoceniana” |
| Zalecane ćwiczenia | wynik planera (zadania naprawcze, powtórki, testy trwałości) | id zadań/umiejętności + powód (który dowód je wywołał) |
| Plan następnej lekcji | `planner.plan()` → `next_plan` | bloki z minutami wg tabeli ARCHITECTURE §4 |

### 6.2 Rola LLM w raporcie
Opcjonalnie jedno wywołanie `generation` zamienia gotowy JSON raportu na 3–5 zdań komentarza PL. Walidator: każda liczba i każdy cytat w narracji musi występować w JSON raportu; zakaz `%` i poziomów CEFR, których nie ma w JSON. Niezgodność → narracja odrzucona, pokazany szablon. Raport zapisany w `session_summary.summary_json` (≤ 300 tokenów wersja do kontekstu + pełna wersja do UI).

## 7. Zmiany w danych (migracja `003_pedagogy.sql`, F4)
Runner migracji wykonuje każdy plik w `BEGIN…COMMIT` przy `foreign_keys=ON`. **Nie wolno przebudowywać tabeli `profile` (DROP/RENAME): `DROP TABLE profile` w tym trybie skasowałby kaskadowo wszystkie dane ucznia.** Dlatego tylko `ALTER TABLE … ADD COLUMN` i nowe tabele:
```sql
ALTER TABLE profile ADD COLUMN correction_style TEXT NOT NULL DEFAULT 'periodic'
  CHECK (correction_style IN ('summary','periodic','intensive'));
UPDATE profile SET correction_style = CASE correction_mode WHEN 'summary' THEN 'summary' ELSE 'periodic' END;
-- correction_mode zostaje (przestarzała, nieczytana przez nowy kod)
ALTER TABLE profile ADD COLUMN allow_unreviewed_practice INTEGER NOT NULL DEFAULT 1 CHECK (allow_unreviewed_practice IN (0,1));

ALTER TABLE skill_state ADD COLUMN status TEXT NOT NULL DEFAULT 'new'
  CHECK (status IN ('new','learning','mastered','retained_7d','retained_30d'));
ALTER TABLE skill_state ADD COLUMN verify_due_at TEXT;
ALTER TABLE skill_state ADD COLUMN verified_7d_at TEXT;
ALTER TABLE skill_state ADD COLUMN verified_30d_at TEXT;
ALTER TABLE skill_state ADD COLUMN relapses INTEGER NOT NULL DEFAULT 0;

ALTER TABLE attempt ADD COLUMN source TEXT NOT NULL DEFAULT 'practice'
  CHECK (source IN ('diagnosis','practice','conversation','correction','retention','remediation'));
ALTER TABLE attempt ADD COLUMN hint_level INTEGER NOT NULL DEFAULT 0 CHECK (hint_level BETWEEN 0 AND 4);

ALTER TABLE error_log ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
  CHECK (status IN ('active','recurring','improving','resolved'));
ALTER TABLE error_log ADD COLUMN severity_max INTEGER NOT NULL DEFAULT 1;
ALTER TABLE error_log ADD COLUMN reopened INTEGER NOT NULL DEFAULT 0;
ALTER TABLE error_log ADD COLUMN example_observation_id INTEGER;

CREATE TABLE observation (
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  session_id INTEGER NOT NULL,
  turn_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('error','natural','variant','stt_suspect','disfluency')),
  category TEXT, skill_id TEXT, span TEXT NOT NULL, fix TEXT,
  severity INTEGER CHECK (severity BETWEEN 1 AND 3),
  confidence TEXT CHECK (confidence IN ('h','m','l')),
  status TEXT NOT NULL DEFAULT 'valid' CHECK (status IN ('valid','dropped')),
  drop_reason TEXT, model TEXT, prompt_version TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (turn_id, session_id, profile_id) REFERENCES turn(id, session_id, profile_id) ON DELETE CASCADE
);
CREATE INDEX observation_session ON observation(profile_id, session_id);

CREATE TABLE turn_meta (
  turn_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
  profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  input_mode TEXT NOT NULL CHECK (input_mode IN ('text','voice')),
  comm TEXT CHECK (comm IN ('ok','partial','fail','na')),
  fluency_json TEXT,      -- tylko metryki zagregowane, bez znaczników czasu pojedynczych słów
  low_prob_words TEXT,    -- JSON listy słów o prob < 0,5 (do walidacji STT)
  PRIMARY KEY (turn_id),
  FOREIGN KEY (turn_id, session_id, profile_id) REFERENCES turn(id, session_id, profile_id) ON DELETE CASCADE
);
```
Nowe tabele mają `profile_id` → objęte istniejącymi testami T-ISO (introspekcja `student_tables`). `content` dalej poza SQLite.

## 8. Moduły `tutor/pedagogy/` (F4)
| Plik | Odpowiedzialność (czyste funkcje / dataclassy) |
|---|---|
| `content.py` | ładowanie i walidacja `content/<lang>/` (schematy pydantic), graf prerekwizytów, filtry statusów |
| `cefr.py` | poziomy, `level_index`, θ↔etykieta, przedział → tekst, sufit/podłoga |
| `diagnosis.py` | siatka bayesowska, wybór zadania, stop, wznowienie z JSON |
| `schemas.py` | TurnEval, RubricScore (pydantic; wejście z LLM walidowane w `app/` przez `structured`) |
| `assessment.py` | `prefilter`, `classify`, oceny wymiarów 0–4, analiza wrażliwości, minimalne dowody |
| `fluency.py` | metryki płynności ze słów ze znacznikami czasu |
| `correction.py` | priorytet, polityka trybów, drabina podpowiedzi (maszyna stanów), sprawdzenie próby |
| `mastery.py` | BKT, statusy, prerekwizyty odblokowane |
| `srs.py` | wrapper `fsrs`, mapowanie ocen |
| `retention.py` | terminy 7/30 dni, dobór niewidzianych zadań, ocena testu |
| `errors.py` | taksonomia, agregacja `error_log`, przejścia statusów |
| `planner.py` | plan sesji (istniejące priorytety + zadania z `stt_suspect`, reuse, `insufficient_evidence`) |
| `report.py` | budowa raportu sesji z danych, walidator narracji |

Wejście/wyjście modułów: dataclassy i dict; zero I/O poza `content.py` (czyta pliki treści — jedyny wyjątek, przekazywany jako ścieżka). Czas wstrzykiwany parametrem `now` (testy deterministyczne).

## 9. Wymagania niefunkcjonalne silnika
- Funkcje `pedagogy/` dla 1 tury < 5 ms (bez LLM); planer < 50 ms przy 500 umiejętnościach i 5000 próbach.
- Ziarno losowe jawne; ten sam stan + `now` + ziarno → ten sam wynik.
- Brak importów `tutor.llm`, `tutor.voice`, `tutor.ui`, `requests` (T-ARCH-1).

## 10. Ryzyka
| Ryzyko | Skutek | Środek |
|---|---|---|
| Bielik słabo wykrywa błędy EN / fałszywe alarmy | uczeń poprawiany niesłusznie | precyzja ponad czułość, walidatory, warianty, brama F8 (§3.3), domyślnie `summary` gdy brama niespełniona |
| Opóźnienie oceny w trybie intensywnym | frustracja | limit 10 s, ocena tylko 1 wypowiedzi, szablony wyjaśnień |
| Nieskalibrowane trudności zadań | zawyżona pewność CEFR | niskie nachylenie, przedział 80%, komunikat „szacunek”, sufit C1 |
| Brak recenzenta ~300 zadań | diagnoza niedostępna | diagnoza włączana per obszar dopiero przy ≥ 15 `human_reviewed` na poziom (A1–C1); ćwiczenia z `ai_checked` z etykietą |
| Błędy STT jako błędy ucznia | niesłuszne korekty | §2.5, reguły 4–5 klasyfikacji, test T-ASSESS-3 |
| Mała liczba uczniów | brak kalibracji IRT | zapisane wprost (§4.4) |

## 11. Kryteria odbioru (wspólne dla F3+F4)
Odbiór = wszystkie poniższe spełnione i sprawdzone poleceniem, nie deklaracją.
1. `.venv/bin/pytest` zielone (dotychczasowe 132 + nowe), `.venv/bin/ruff check .` czyste.
2. T-ARCH-1/2, T-LANG-1 zielone.
3. Migracja 003: test od pustej bazy i od v2 z danymi; liczba wierszy wszystkich tabel ucznia przed = po; `correction_mode='immediate'` → `correction_style='periodic'`; backup utworzony.
4. Walidator treści (`python main.py content validate en`) przechodzi; raportuje liczbę zadań per (obszar × poziom × status).
5. Żadne zadanie z `provenance.source=ai_generated` nie ma `human_reviewed` bez `reviewer` z `reviewers.yaml` i `reviewed_at`; test, że generator nie potrafi ustawić tych pól.
6. Katalog umiejętności: ≥ 80 umiejętności w 5 domenach, graf acykliczny, każda kategoria błędu z `skills` istnieje w `errors.yaml`.
7. Bank pilotażowy: 3 zadania na (obszar grammar/vocabulary/reading/listening × poziom A1–C1) = 60, wszystkie poprawne schematowo; **nie** cały bank. Status wg rzeczywistości (`draft`/`ai_checked`), nic nie oznaczone jako `human_reviewed` przez AI.
8. Testy T-PED-*, T-ASSESS-*, T-CORR-*, T-RET-*, T-REPORT-* z TEST_PLAN zielone.
9. Raport sesji z fikstury (FakeProvider + nagrane obserwacje) nie zawiera żadnej liczby, której nie ma w danych wejściowych (test), i nie zawiera słowa „wymowa” w kontekście oceny pozytywnej.
10. Brak sekretów i danych osobowych w commitach (`git diff main... | grep -iE 'key|token|@'` przejrzane).

## 12. Co NIE wchodzi do F3/F4
Integracja z kolejką oceny i rozmową głosową (`app/`, F5), `transcribe_detailed()` (F5), GUI (F6), pełny bank ~300 zadań (wymaga recenzenta), kalibracja IRT, C2, ocena wymowy, Gemini.
