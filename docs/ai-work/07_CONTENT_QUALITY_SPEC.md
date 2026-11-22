# Moduł 07 (F4.5) – Otwarte materiały dydaktyczne i brama jakości oceny

Gałąź `feat/content-quality-design` (z `main` = `origin/main` = `40cf348`). Dokument projektowy: **nic z tego nie jest jeszcze zaimplementowane**. Wdrożenie: F4.6 wg `F4_6_SONNET_BRIEF.md`. Źródła prawdy wyżej w hierarchii: decyzje w `HANDOFF.md` i `04_PEDAGOGY_SPEC.md`. Ten dokument je rozszerza; przy sprzeczności wygrywa spec 04, chyba że niżej wprost zapisano zmianę decyzji (§8).

Zasady nadrzędne bez zmian: silnik F4 (`tutor/pedagogy/`) czysty i deterministyczny; LLM obserwuje, kod liczy; Bielik 11B domyślny; bez RAG, agentów, baz wektorowych; Gemini odroczony; moduł głosowy bez przebudowy; nic AI nie dostaje `human_reviewed`.

## 0. Stan wyjściowy (sprawdzony 2026-11-22)
- `main` = `origin/main` = `40cf348`. Gałęzie `feat/f0-scaffold`, `feat/voice-prototype`, `feat/pedagogy-design`, `feat/f3-content`, `feat/f4-pedagogy` są **w całości scalone** do `main` (`git merge-base --is-ancestor` = tak dla każdej). HANDOFF twierdził „bez scalania” — poprawione. Scalania nie powtarzano.
- Treść: 115 umiejętności, 60 zadań (49 `ai_checked`, 11 `draft`, 0 `human_reviewed`), 15 wyjaśnień PL, 49 kategorii błędów, `vocab` (tabela per profil) istnieje, ale nie ma listy słownictwa w treści.
- Maszyna: brak Javy (`java` nie znaleziona), 31 GiB RAM (~20 GiB dostępne przy pracy), Bielik 11B częściowo na CPU (offload) — **każdy dodatkowy proces CPU konkuruje z generowaniem rozmowy**.
- Repo nie ma pliku `LICENSE`. Ma to znaczenie dla treści CC BY-SA (§1.3).

## 1. Materiały źródłowe

### 1.1 Rejestr i licencje (zweryfikowane)
Biblioteka lokalna: `~/.local/share/english-ai-tutor/content_sources/` (`REGISTRY.md`, `SHA256SUMS`), poza Git.

| id źródła | Dzieło | Autorzy | Licencja (zweryfikowano) | Wyjątki | Format do importu |
|---|---|---|---|---|---|
| `esol` | A Digital Workbook for Beginning ESOL (2018) | Eric Dodson, Davida Jordan, Tim Krause | CC BY 4.0, „except where otherwise noted” (strona redakcyjna PDF + strona książki) | osadzone wideo (YouTube oEmbed) i H5P → **nie używać** | Pressbooks **XHTML** lub EPUB: `https://openoregon.pressbooks.pub/esol23/` (menu „Download this book”: EPUB, PDF, XHTML, Pressbooks XML, WordPress XML) |
| `greentea` | Green Tea Intermediate English Communication OER (2020) | Eric Dodson, Luciana Diniz, Nanci Leiton | CC BY 4.0, „except where otherwise noted” | wideo i aktywności H5P → **nie używać** | XHTML/EPUB: `https://openoregon.pressbooks.pub/greentea/` |
| `twe` | Technical Writing Essentials (2019) | Suzan Last | CC BY 4.0, „except where otherwise noted” | lista wyjątków „noncommercial, educational use only”: S.1 (fragment Wells), Fig. 1.5.1, 3.4.1, 3.4.2, 5.2.1, 5.2.2, 5.3.1, 7.4.1 → **wykluczone** | XHTML/EPUB: `https://pressbooks.bccampus.ca/technicalwriting/` |
| `brehe` | Brehe's Grammar Anatomy (v2, ISBN 978-1-940771-49-6) | Steven Brehe (UNG Press / University System of Georgia) | CC BY-SA 4.0 — **wg strony redakcyjnej PDF**; strona UNG licencji nie podaje | nota PDF: licencja nie obejmuje włączonych treści na innych licencjach CC (np. ND) ani „special permissions” → używać **tylko tekstu autora**, bez obrazów, rycin i cytatów obcych | tylko PDF (UNG nie oferuje EPUB/HTML; link SharePoint niestabilny). Import z lokalnego PDF z normalizacją ligatur (`fi`, `fl`, `ff`) |
| `ngsl` | New General Service List 1.2 (2809 słów) | Charles Browne, Brent Culligan, Joseph Phillips | CC BY-SA 4.0 (strona NGSL) | brak per-plik; zakładamy objęcie wszystkich list | CSV/XLSX (pliki oficjalne) |
| `ngsl_s` | NGSL-Spoken 1.2 (721 słów, ~90% pokrycia mowy nieskryptowanej) | Charles Browne, Brent Culligan | CC BY-SA 4.0 (strona NGSL-S) | — | CSV oficjalne: `NGSL-Spoken_12_lemmatized_for_teaching.csv`, `..._stats.csv` (rangi), `..._with_en_definitions.csv` |
| `sup` | SUP_lemmatized.csv | prawdopodobnie NGSL | strona NGSL opisuje „52 supplementary words” bez rang, licencji osobno nie podaje | — | **pomijany** do potwierdzenia pochodzenia (decyzja użytkownika) |

Wnioski:
- NGSL-Spoken **można użyć** (ta sama licencja CC BY-SA 4.0, oficjalne CSV). Pliki nie są w bibliotece lokalnej — do pobrania w F4.6 (C1), z wpisem do `REGISTRY.md` i `SHA256SUMS`.
- Lokalne pliki NGSL **nie zawierają rang częstości**: CSV „teaching/research” są alfabetyczne, a kolejność wierszy XLSX nie jest ani alfabetyczna, ani udokumentowana. Rangi daje tylko oficjalny `NGSL_12_stats.csv` („includes frequency rankings”) — do pobrania w C1. Bez niego pole `rank` = `null` i nic nie zakłada częstości.
- Atrybucja NGSL wg strony: „Browne, C., Culligan, B., & Phillips, J. — The New General Service List 1.2, newgeneralservicelist.com, CC BY-SA 4.0”.

### 1.2 Zasady importu
1. **Format**: XHTML/EPUB z Pressbooks zamiast PDF (struktura rozdziałów, brak ligatur, czysty tekst). Brehe: tylko PDF → `pdftotext -layout` + normalizacja ligatur + ręcznie sprawdzona mapa stron → sekcji.
2. **Ekstrakcja poza repo**: `tools/source_extract.py` zapisuje fragmenty (rozdział/sekcja, ≤ 1500 tokenów, `sha256` pliku źródłowego, numer strony lub id sekcji) do `~/.local/share/english-ai-tutor/content_sources/extracted/<id>.jsonl`. **Nigdy do Git.** Stdlib (`zipfile`, `html.parser`), bez nowych zależności.
3. **Wykluczenia** w `tutor/content/en/sources.yaml` (`exclude:` — sekcje/ryciny z wyjątkami licencyjnymi, media osadzone, materiały z innych licencji). Ekstraktor pomija je i loguje.
4. **Do LLM idzie tylko jeden fragment naraz** (sekcja dobrana ręcznie przez mapę §2.3), nigdy cała książka ani rozdział > 1500 tokenów.
5. **Bez kopiowania**: treść w repo jest **własną adaptacją** (parafraza, inne przykłady, wyjaśnienie PL). Walidator odrzuca fragmenty wspólne ze źródłem ≥ 12 kolejnych słów (poza listą terminów i przykładami jednozdaniowymi z atrybucją). Krótkie przykłady zdaniowe wolno przejąć z atrybucją (licencje to dopuszczają), ale preferowane są własne.
6. **Sumy kontrolne**: każde odwołanie zapisuje wersję źródła = SHA-256 pliku, z którego wyciągnięto fragment. Zmiana pliku → walidator zgłasza „źródło zmienione, przejrzyj odwołania”.

### 1.3 Licencje treści w repo
- Treść adaptowana z CC BY 4.0 (`esol`, `greentea`, `twe`): atrybucja wystarcza; plik może mieć dowolną licencję zgodną.
- Treść adaptowana z CC BY-SA 4.0 (`brehe`, `ngsl`, `ngsl_s`): **utwór zależny musi być na CC BY-SA 4.0**. Dlatego:
  - plik słownictwa `tutor/content/en/vocab/ngsl.csv` i każdy plik/zadanie z odwołaniem do `brehe` ma `license: CC-BY-SA-4.0`;
  - walidator: element z `refs` do źródła SA musi mieć `license: CC-BY-SA-4.0`; element mieszający źródła CC BY i CC BY-SA → CC BY-SA.
- Nowy plik `tutor/content/en/ATTRIBUTION.md` generowany z `sources.yaml` (tytuł, autorzy, URL, licencja, wersja/SHA, „zmodyfikowano: adaptacja i tłumaczenie wyjaśnień na polski”).
- **Ryzyko do decyzji użytkownika (nie blokuje F4.6):** repo publiczne bez `LICENSE`. Kod pozostaje „wszystkie prawa zastrzeżone”, a treść ma licencje per plik. Rekomendacja: dodać `LICENSE` dla kodu i `tutor/content/LICENSE.md` opisujący licencje treści; F4.6 tego nie robi bez decyzji.

## 2. Biblioteka dydaktyczna

### 2.1 Rozszerzenie schematu (minimalne, uzasadnione)
Schemat F3 zostaje. Zmiany wymuszone licencjami (atrybucja) i spec 04 §2.9 („karta FSRS `construction`, jeśli fraza z listy treści” — listy nie ma):

| Zmiana | Gdzie | Uzasadnienie |
|---|---|---|
| `Provenance.source` += `ai_adapted` | `content.py` | odróżnia adaptację źródła od generacji „z głowy”; nadal startuje jako `draft` |
| `Provenance.refs: list[{src, loc, sha}]` (opcjonalne) | items, scenarios, grammar front matter, phrases | wymóg atrybucji CC; `loc` = id sekcji lub strona |
| `license: str` (opcjonalne; wymagane, gdy `refs` niepuste) | jw. + pliki CSV | ShareAlike |
| nowy `sources.yaml` | `tutor/content/en/` | rejestr źródeł w repo (bez tekstów): id, tytuł, autorzy, URL, licencja, sha256, `exclude` |
| nowy `phrases.yaml` | `tutor/content/en/` | zwroty i kolokacje (§2.4) dla kart `construction` i celów rozmowy |
| nowy `vocab/ngsl.csv` | `tutor/content/en/vocab/` | lista słownictwa (§3) |

Statusy bez zmian (`draft/ai_checked/human_reviewed/rejected/suspect`). **`ai_adapted` nie może mieć `human_reviewed` bez `reviewer` i `reviewed_at` z CLI `content review`** (rozszerzenie T-CONTENT-3). Wyjaśnienia, scenariusze i zwroty dostają ścieżkę w `content review` (dziś obsługuje tylko zadania; F3 pkt 9 odłożył to do czasu recenzenta — teraz potrzebne, bo pilotaż daje te typy).

### 2.2 Rodzaje treści i ich miejsce
| Rodzaj | Plik | Struktura | Status startowy |
|---|---|---|---|
| Wyjaśnienie gramatyczne PL | `grammar/<slug>.md` | front matter (`provenance`, `review`, `license`, `refs`) + sekcje stałe: `Zasada`, `Formy`, `Poprawnie` (≥ 4 zdania), `Błędnie → poprawnie` (≥ 4 pary z kategorią błędu), `Typowe błędy Polaków` (≥ 2, każdy z id kategorii z `errors.yaml`), `BrE/AmE` (gdy dotyczy), `Źródła` | `draft` |
| Ćwiczenia z kluczem | `items/<area>/<cefr>.yaml` | schemat F3; klucz z wariantami; `explanation_pl` | `draft` → `ai_checked` (kontrola na ślepo) |
| Pula trwałości | jw., `pools: [retention]` | rozłączna z `practice` (walidator F3) | jw. |
| Typowe błędy Polaków | `errors.yaml` (istniejące pola `explanation_pl`, `l1`, `l2_pl`) + nowe podkategorie `l1_calque.*` (np. `l1_calque.make_photo`, `l1_calque.have_years`) | bez zmiany schematu | treść AI-draft |
| Konwersacje, zwroty naturalne | `scenarios/*.yaml` (`example_phrases`) + `phrases.yaml` | §2.4 | `draft` |
| Angielski techniczny/zawodowy | `skills/tech_it.yaml`, `interview.yaml` + zadania + zwroty z `twe` | jw. | `draft` |
| Źródła, wersje, licencje | `sources.yaml`, `refs`, `license`, `ATTRIBUTION.md` | §1.3 | — |

Walidator sprawdza strukturę `.md` (nagłówki sekcji, liczby przykładów, istniejące kategorie, każda para „Błędnie” ma poprawkę i nie jest identyczna).

### 2.3 Mapa źródło → umiejętności (rola każdego źródła)
| Źródło | Do czego | Poziomy | Umiejętności (przykłady) |
|---|---|---|---|
| `esol` | gramatyka podstawowa, słownictwo codzienne, proste teksty | A1–A2 | `to_be_present`, `present_simple`, `there_is_are`, `past_simple_regular`, `en.vocab.daily_routine` |
| `greentea` | strategie rozmowy, zwroty, funkcje językowe | A2–B1 | `en.conv.ask_clarification`, `agree_disagree`, `give_opinion`, `greetings_small_talk` |
| `brehe` | terminologia i struktura zdania; wyjaśnienia dla wyższych poziomów (adaptowane na PL) | B1–C1 | `present_perfect`, `passive_basic`, `relative_non_defining`, `participle_clauses` |
| `twe` | e-mail, raport, dokumentacja, styl zwięzły; strona bierna w raportach | B1–C1 | `en.tech.client_email`, `incident_report`, `documentation` |
| `ngsl`, `ngsl_s` | warstwa słownictwa (§3) | wszystkie | wszystkie `en.vocab.*`, cele słownikowe rozmowy |

Mapa w `sources.yaml` jako `map: {skill_id: [{src, loc}]}` (tylko lokalizacje, bez tekstu). Ręcznie przejrzana przy pilotażu.

### 2.4 `phrases.yaml`
```yaml
- id: en.phr.could_you_clarify
  text: "Could you clarify what you mean by …?"
  pattern: '\bcould you (clarify|explain)\b'    # detekcja użycia (opcjonalnie)
  kind: phrase            # phrase | collocation | chunk
  skill_ids: [en.conv.ask_clarification]
  register: neutral       # informal | neutral | formal
  variety: both           # both | BrE | AmE
  gloss_pl: "Czy możesz doprecyzować, co masz na myśli…?"
  lemmas: [could, clarify, mean]   # powiązanie z NGSL
  provenance: {source: ai_adapted, model: …, refs: [{src: greentea, loc: "ch3.s2", sha: …}]}
  license: CC-BY-4.0
  review: {status: draft}
```
Karty FSRS `construction` powstają tylko z `phrases.yaml` (`usable(..., "practice")`) lub z poprawki zaakceptowanej przez ucznia (spec 04 §2.9).

### 2.5 Pilotaż: 12 umiejętności
| # | Umiejętność | CEFR | Źródła | Związek |
|---|---|---|---|---|
| 1 | `en.gram.to_be_present` | A1 | esol | podstawa, typowy błąd: brak łącznika |
| 2 | `en.gram.present_simple` | A1 | esol | -s w 3. os. |
| 3 | `en.gram.articles_basic` | A1 | esol, brehe | błąd nr 1 Polaków; zadanie F3 `gram.a1.03` |
| 4 | `en.vocab.daily_routine` | A1 | esol, ngsl | test słownictwa + karty |
| 5 | `en.gram.past_simple_regular` | A2 | esol | zadanie F3 `gram.a2.01` |
| 6 | `en.gram.present_perfect` | B1 | brehe, esol | `gram.b1.01`; BrE/AmE (just/already) |
| 7 | `en.conv.ask_clarification` | B1 | greentea | zwroty, cel rozmowy |
| 8 | `en.conv.agree_disagree` | B1 | greentea | zwroty, rejestr |
| 9 | `en.vocab.collocations_make_do` | B1 | ngsl, własne | kolokacje, kalki PL (`make a photo`) |
| 10 | `en.gram.passive_basic` | B2 | brehe, twe | strona bierna w raportach |
| 11 | `en.tech.incident_report` | B2 | twe | angielski zawodowy |
| 12 | `en.gram.participle_clauses` | C1 | brehe | wyższy poziom |

Na każdą umiejętność (zakres pilotażu, nie pełny bank):
- 1 wyjaśnienie PL wg §2.2 (dla 1–3, 5, 6, 12 już istnieje — rozbudować do nowej struktury);
- ≥ 4 zdania poprawne i ≥ 4 pary „błędnie → poprawnie”;
- ≥ 2 typowe błędy Polaków z kategorią;
- 4 zadania `practice` (≥ 2 produkcyjne) + 3 zadania `retention` (≥ 1 produkcyjne; rozłączne z `practice`; pierwszy raz pula `retention` w banku);
- dla 4, 7–9, 11: ≥ 6 zwrotów/kolokacji w `phrases.yaml`;
- `refs` + `license` przy wszystkim, co adaptowane.

Razem ≈ 84 nowe zadania, 12 wyjaśnień, ~40 zwrotów. Wszystko `draft`; kontrola na ślepo może dać `ai_checked`. **Bez pełnego banku 300 zadań i bez `human_reviewed`.** Pilotaż nie zmienia bramy diagnozy (T-CONTENT-2) — zadania pilotażowe są w pulach `practice`/`retention`, nie `diagnosis`.

## 3. Słownictwo

### 3.1 Import (`tools/import_ngsl.py`, deterministyczny, bez LLM)
Wejście: `NGSL_1.2_lemmatized_for_teaching.csv` (nagłówek `##` pomijany; wiersz = lemat + formy), `NGSL_1.2_with_English_definitions.xlsx` (2 kolumny `Word`, `Definitons`; parsowanie stdlib `zipfile`+`xml.etree`, **bez openpyxl**), opcjonalnie `NGSL_12_stats.csv` (rangi) i NGSL-Spoken CSV. Wyjście: `tutor/content/en/vocab/ngsl.csv` (CC BY-SA 4.0, nagłówek z atrybucją i SHA plików wejściowych):

| kolumna | Źródło | Uwagi |
|---|---|---|
| `lemma` | teaching CSV, kol. 1 | nagłówek w pisowni US (wg opisu NGSL) |
| `forms` | teaching CSV | wszystkie formy, w tym brytyjskie (`colour, coloured…`) |
| `variants` | wyliczone | pary BrE/AmE wykryte regułami (`our/or`, `ise/ize`, `yse/yze`, `re/er`, `ll/l`, `ogue/og`) **i** potwierdzone obecnością obu form w `forms`; inaczej puste |
| `definition_en` | XLSX | jedna definicja „easy English”, **jedno znaczenie** |
| `homograph` | lista z nagłówka CSV (`found, left, mine, rose, wound`) + lematy z formami innych lematów (`bear/born`) | wykluczone z automatycznego testu rozpoznawania; definicja może nie pasować do najczęstszego sensu |
| `rank` | `NGSL_12_stats.csv` | puste, gdy brak pliku. **Nigdy z kolejności wierszy** (alfabet w CSV, nieudokumentowana kolejność w XLSX) |
| `freq_band` | z `rank`: 1 (1–500), 2 (501–1000), 3 (1001–2000), 4 (2001+) | puste bez `rank` |
| `spoken` | NGSL-Spoken | `1`/`0`/puste |
| `cefr` | — | **zawsze puste.** Częstość ≠ poziom CEFR. Poziom słowa pojawia się wyłącznie przez umiejętność (`skill_ids`) lub ręczną recenzję |
| `gloss_pl` | — | puste. Glosy PL nie są częścią źródła; generowane AI tylko na żądanie lekcji, jako `draft` w `vocab.meaning_pl` ucznia, oznaczone „tłumaczenie maszynowe” |

Walidator: 2809 lematów, unikalne, każdy lemat ma definicję albo flagę `no_definition`, `rank` unikalny gdy obecny.

### 3.2 Stan wiedzy ucznia (migracja `004_vocab.sql`, tylko `ADD COLUMN`)
Istniejąca tabela `vocab(profile_id, lang, term, meaning_pl, example, source)` dostaje:
- `lemma TEXT` (klucz do `ngsl.csv`, NULL dla słów spoza listy),
- `knowledge TEXT NOT NULL DEFAULT 'unknown' CHECK (knowledge IN ('unknown','passive','active'))`,
- `seen_count`, `recall_ok`, `recall_fail`, `used_count INTEGER NOT NULL DEFAULT 0`, `last_used_at TEXT`.
Bez nowych tabel; `profile_id ON DELETE CASCADE` już jest → T-ISO bez zmian.

Przejścia (czyste funkcje, `tutor/pedagogy/vocab.py`):
- `passive` (wiedza bierna): rozpoznanie — poprawne MC znaczenia, „tak” w teście rozpoznawania potwierdzone kontrolą (§3.3) albo poprawne zrozumienie w zadaniu reading/listening, gdzie słowo jest kluczem.
- `active` (wiedza czynna): ≥ 2 poprawne przywołania produkcyjne (PL→EN, luka) w różnych dniach **lub** ≥ 2 poprawne użycia w rozmowie w różnych sesjach (§3.5).
- Spadek: 2 kolejne porażki przywołania → `passive`. `active` nigdy nie wraca do `unknown`.

### 3.3 Rozpoznawanie znanego słownictwa
Test „tak/nie” z pseudosłowami (metoda typu yes/no): ~40 słów z listy + 10 pseudosłów.
- Próbka warstwowa po `freq_band` (wymaga `rank`; bez niego warstwy wg `spoken` i dziedziny umiejętności, a wynik oznaczony „bez rang — przybliżenie”).
- Pseudosłowa w `vocab/pseudowords.yaml`, **`human_reviewed` wymagane** (pseudosłowo przypadkiem będące słowem psuje korektę). Do recenzji test działa tylko jako „wstępny”.
- Korekta zgadywania: wynik = trafienia − fałszywe „tak” na pseudosłowach (prosta korekta h−f); przy fałszywych „tak” ≥ 30% wynik odrzucony („odpowiedzi niewiarygodne”).
- Słowa z „tak” → `passive` tylko w warstwach, gdzie skorygowany wynik ≥ 0,8; reszta pozostaje `unknown`. **Nie tworzy kart.** Wynik: szacowany odsetek znanych słów per warstwa, bez CEFR.

### 3.4 FSRS bez masowych kart
Żadnego automatycznego tworzenia 2809 kart. Karta `vocab` (przywołanie czynne, `ref_id` = lemat) powstaje tylko, gdy:
1. słowo jest celem lekcji (umiejętność `en.vocab.*`, zadanie z kluczem) i uczeń je ćwiczył,
2. uczeń nie przywołał słowa w zadaniu produkcyjnym,
3. TurnEval/LanguageTool zgłosił `word_choice`/`collocation` z tym lematem w poprawce (pewność h/m, po walidatorach),
4. uczeń dodał słowo ręcznie.

Limity w `rubric.yaml` (`srs.vocab_new_per_day: 10`, `srs.vocab_max_active: 300`). Wiedza bierna nie ma kart (tania, bez powtórek). Zwroty i kolokacje → karty `construction` z `phrases.yaml` (§2.4), też tylko po ekspozycji w lekcji.

### 3.5 Słowa w rozmowie
- Planer dodaje do `plan_json` `vocab_targets` (≤ 5): karty zaległe + słowa nowe z lekcji; obok istniejących `reuse_targets`.
- Prompt rozmowy dostaje listę i instrukcję stworzenia okazji (jak uptake, spec 04 §3.2).
- Detekcja deterministyczna: dopasowanie form z `forms` (z wariantami BrE/AmE) w **formie końcowej po prefiltrze** wypowiedzi ucznia; nie liczy się, gdy słowo wystąpiło w poprzedniej wypowiedzi tutora w tej samej turze w identycznym zwrocie ≥ 3 słów (echo), w fragmencie `disfluency` albo przy prob Whispera < 0,5.
- Użycie poprawne (brak obserwacji `error` na tym spanie) → `used_count += 1`, karta (jeśli jest i zaległa) → Good. Błędne użycie → obserwacja zwykłą ścieżką.

## 4. LanguageTool (opcjonalny, lokalny)

### 4.1 Fakty (zweryfikowane w dokumentacji) i braki
- Rdzeń LGPL 2.1+; serwer HTTP `org.languagetool.server.HTTPServer` z paczki `LanguageTool-*.zip` (snapshot „bez reguł AI”, które istnieją tylko w chmurze). Domyślnie **niedostępny z innych hostów** (dostęp zdalny dopiero z `--public`). Opcje: `--port`, `--config server.properties`, `--allow-origin` (nie używać). Obraz Docker tylko społecznościowy → nie używamy.
- Java: dokumentacja serwera mówi „Java 8+”, README budowania „Java 17” → przyjmujemy JRE 17 (`openjdk-17-jre-headless`, wymaga `sudo`, decyzja użytkownika). Na maszynie brak Javy.
- **Niezweryfikowane w dokumentacji (strona API renderowana JS)** — sprawdzić na zainstalowanej wersji w F4.6/C4 (`--help`, odpowiedź `/v2/check`): parametry `language`, `text`, `motherTongue`, `preferredVariants`, `enabledRules`/`disabledRules`, `enabledCategories`/`disabledCategories`, `enabledOnly`, `level`; pola odpowiedzi `matches[].{offset,length,message,replacements[].value,rule.{id,issueType,category.id}}`; klucze `server.properties` (`cacheSize`, `pipelineCaching`, `maxTextLength`, `maxCheckThreads`); zużycie RAM; czy `language=en` (bez odmiany) wyłącza sprawdzanie pisowni; czy istnieją reguły false friends dla `motherTongue=pl`. Projekt niżej zakłada te nazwy; adapter ma test kontraktu na zapisanej odpowiedzi z prawdziwego serwera.

### 4.2 Architektura (bez obowiązkowej zależności)
```
uczeń → rozmowa (Bielik stream → TTS)            # LT nigdy nie stoi na tej ścieżce
      → kolejka oceny (app/, 1 wątek, po zakończeniu strumienia rozmowy)
          1. prefiltr
          2. LT /v2/check   (opcjonalnie, timeout 1,5 s, brak → pomijamy)   ← nowe
          3. TurnEval Bielik (jak dziś)
          4. merge(lt, bielik) → kandydaci obserwacji                       ← nowe, czysta funkcja
          5. classify() i walidatory (bez zmian: span, warianty, STT, disfluency)
          6. zapis, polityka korekty, aktualizacje (z bramą §5.5)
```
- `tutor/app/languagetool.py` (~60 linii): `check(text, lang_variant) -> list[LTMatch] | None`. `requests` (już jest), `POST` na `config.toml [languagetool] url` (domyślnie `http://127.0.0.1:8081`). Walidacja: host ∈ {`127.0.0.1`, `localhost`, `::1`}, inaczej błąd konfiguracji (nigdy chmura, nigdy publiczne API LanguageTool). `enabled = false` domyślnie. Błąd/timeout → `None` + jeden wpis w logu na sesję; ocena idzie dalej samym Bielikiem.
- `tutor/pedagogy/lt_merge.py` (czysta funkcja, bez I/O): mapowanie i rozstrzyganie (§4.4–§4.5). T-ARCH-1 obowiązuje.
- Uruchamianie serwera: **ręcznie przez użytkownika** albo jednostka `systemd --user` z dokumentacji (`nice -n 10`, `-Xmx` do pomiaru, start: 512m), port 8081 na `127.0.0.1`. Aplikacja nie instaluje, nie pobiera i nie uruchamia LT. `main.py lt status` (opcjonalne) — tylko ping.
- Zasoby: `maxCheckThreads=1`, `maxTextLength` 2000, cache wyników po stronie serwera; wywołanie tylko z kolejki oceny, więc nie konkuruje z generowaniem w czasie streamu. Pomiar w benchmarku (§5) decyduje, czy LT zostaje włączalny: RSS ≤ 1 GiB, p95 ≤ 300 ms na wypowiedź, spadek tok/s Bielika przy równoległym LT nie dotyczy (sekwencyjnie), wpływ na TTFT rozmowy ≤ 5% (mierzony).

### 4.3 Mowa potoczna vs błąd
Konfiguracja wywołania (`content/en/lt_map.yaml`, wersjonowane):
- wyłączone kategorie zawsze: style, redundancja, typografia, „plain English”, kolokwializmy, wielkość liter na początku zdania w mowie;
- wejście głosowe: dodatkowo pisownia, interpunkcja, wielkie litery (spec 04 §2.3 reguła 4 i tak je odrzuca — wyłączenie oszczędza CPU);
- lista dozwolonych form potocznych w `disfluency.yaml`/`variants.yaml` (`gonna`, `wanna`, `gotta`, `yeah`, `kinda`, zdanie od `And/But`, elipsa w odpowiedzi „Sounds good.”) — dopasowanie → `variant`, nie błąd;
- reguły „sugestii stylu” (`issueType` = style/locale-violation itp.) nigdy nie stają się `error`.

### 4.4 Mapowanie reguł → taksonomia
`lt_map.yaml`:
```yaml
lt_map_version: lt_map.v1
lt_version_tested: null          # wpisać po instalacji
rules:                           # rule.id → kategoria + zaufanie + czy dla głosu
  EN_A_VS_AN:            {category: article.wrong, trust: h, voice: false}   # w mowie to kwestia wymowy/STT
  HE_VERB_AGR:           {category: agreement.subject_verb, trust: m, voice: true}
  NON3PRS_VERB:          {category: agreement.subject_verb, trust: m, voice: true}
  DT_DT:                 {category: determiner, trust: m, voice: false}      # często powtórzenie
categories:                      # rule.category.id → domyślne mapowanie, gdy reguła nie wpisana
  GRAMMAR:   {category: null, trust: l}     # nieznana reguła gramatyczna → l (tylko log)
  TYPOS:     {category: spelling, trust: m, voice: false}
  CONFUSED_WORDS: {category: word_choice, trust: l, voice: false}
  COLLOCATIONS: {category: collocation, trust: l}
ignore_categories: [STYLE, REDUNDANCY, TYPOGRAPHY, CASING, PLAIN_ENGLISH, COLLOQUIALISMS, PUNCTUATION]
```
Nazwy identyfikatorów do potwierdzenia na zainstalowanej wersji (C4). Reguła nieznana → ignorowana i liczona w statystyce „niezmapowane” (lista do uzupełnienia, nie zgadujemy kategorii). Kategoria docelowa musi istnieć w `errors.yaml` (walidator).

Pisownia BrE/AmE: wywołanie z `language=en-US` dla tekstu (lub `en` bez pisowni — do sprawdzenia); dopasowanie `TYPOS` jest odrzucane jako `variant`, gdy słowo występuje w `forms` NGSL, w `variants.yaml` albo przechodzi reguły BrE→AmE z §3.1. Tak BrE i AmE są równorzędne bez dwóch wywołań.

### 4.5 LanguageTool nie jest źródłem prawdy — rozstrzyganie z Bielikiem
Dopasowanie LT → kandydat obserwacji: `span = text[offset:offset+length]`, `fix` = pierwsza zamiana, `kind=error`, `category`/`p` z `lt_map`, `model = "languagetool-<wersja>"`. Następnie `lt_merge.merge(bielik_obs, lt_obs)`:

| # | Sytuacja (nakładanie spanów po normalizacji) | Wynik |
|---|---|---|
| R1 | Bielik i LT zgłaszają ten sam span, zgodna kategoria (ten sam rdzeń taksonomii) | jedna obserwacja, poprawka Bielika (jeśli przechodzi walidatory, inaczej LT), pewność +1 stopień (max `h`), `model="bielik+lt"` |
| R2 | ten sam span, różna kategoria lub poprawka | obserwacja Bielika bez zmian; alternatywa LT tylko w logu benchmarku |
| R3 | tylko Bielik | bez zmian (zachowanie F4) |
| R4 | tylko LT, reguła `trust: h`, wejście tekstowe | obserwacja z `p = m` |
| R5 | tylko LT, pozostałe przypadki (trust m/l, głos) | `p = l` → widoczna jako sugestia w analizie, **nie** wchodzi do `error_log`/BKT (istniejąca reguła §2.8) |
| R6 | LT zgłasza span, który Bielik oznaczył jako `variant`/`natural`, albo `classify` daje `variant`/`disfluency`/`stt_suspect` | wygrywa klasyfikacja deterministyczna; LT nie podnosi do `error` |
| R7 | Bielik oznaczył konstrukcję celu `t: ok`, LT zgłasza błąd w tym spanie | `p = l` dla LT; brak zmiany `t` |

Jedna obserwacja na span (zgodne z unikalnym indeksem `observation_dedupe`). Kategorie i reguły z R4 dostają `trust: h` dopiero po benchmarku (§5.5); do tego czasu `lt_map` startuje bez żadnego `h` w praktyce produkcyjnej — `trust` w pliku jest hipotezą do zmierzenia. Konfiguracja: `rubric.yaml correction.quality_gate.lt_trusted_rules: []`.

Ignorowanie niepewnych błędów STT: nic nowego — kandydaci LT przechodzą przez `classify()` (reguły 4–5: pisownia/interpunkcja w mowie odrzucona; słowo z prob < 0,5, pary z `stt_confusables.yaml`, brzegi wypowiedzi → `stt_suspect`).

## 5. Benchmark jakości przed F5

### 5.1 Zestaw `bench/cases/en/grammar_gold.yaml` (130 + 11)
Niezależny od banku zadań i od Bielika: zdania pisane przez człowieka lub przez Claude jako `draft`, a **wynik liczy się tylko na przypadkach `human_reviewed`** (recenzja złotego standardu = osobna, krótka ścieżka w `content review`/`bench review`). Żaden przypadek nie pochodzi z wypowiedzi uczniów (brak danych osobowych) ani z tekstu podręczników.

| Podzbiór | n | Cel |
|---|---|---|
| E1 – jeden błąd, typowy dla Polaków (rodzajniki, czasy, przyimki, szyk, zgodność, kalki, policzalność, `since/for`, `make/do`) | 45 | precyzja, czułość, poprawność korekty |
| E2 – 2–3 błędy w zdaniu | 15 | czułość przy wielu błędach, zachowanie znaczenia |
| C1 – zdania poprawne, standardowe | 25 | false positive rate |
| C2 – poprawne warianty: BrE/AmE (pisownia, słownictwo, `have got`, `gotten`, present perfect vs past simple z `just`), kontrakcje, `who/whom`, zdania eliptyczne | 15 | akceptacja BrE/AmE |
| C3 – potoczne poprawne w mowie (`gonna`, `yeah`, zdanie od `And`, fragmenty odpowiedzi) | 10 | mowa potoczna ≠ błąd |
| S – transkrypcje głosowe z błędami STT (brak `a/the`, `-s/-ed`, `can/can't`, `there/their`), z prob słów; złoty standard: 0 błędów ucznia | 12 | zachowanie wobec STT |
| D – wypełniacze, powtórzenia, autonaprawy (`I goed— I went`) | 8 | disfluency ≠ błąd |
| **Razem** | **130** | |
| F3 – 11 niezgodności z kontroli banku F3 (lista niżej) | 11 | osobna miara: sędzia zadań |

Format przypadku:
```yaml
- id: g.e1.017
  set: E1
  input_mode: text            # text | voice
  text: "I have 25 years and I work in IT."
  words: null                 # voice: [[word, start, end, prob], ...]
  gold:
    - {span: "I have 25 years", fix_accept: ["I am 25", "I'm 25", "I am 25 years old", "I'm 25 years old"], category: l1_calque, severity: 2}
  meaning: "wiek mówiącego: 25 lat"
  variety: any                # any | BrE | AmE
  review: {status: draft, reviewer: null, reviewed_at: null}
```

Podzbiór F3 (zadania z `solve_check: niezgodność`): `en.pilot.gram.a1.03`, `gram.a2.01`, `gram.b1.01`, `gram.b1.02`, `gram.b2.01`, `gram.c1.01`, `gram.c1.02`, `listen.a1.02`, `read.a1.01`, `vocab.a1.02`, `vocab.b2.03`. Wstępny przegląd (do potwierdzenia przez człowieka): klucze wyglądają na poprawne, niezgodność to najpewniej błąd sędziego (Bielik), z jednym wyjątkiem do recenzji — `vocab.b2.03` (`cut to the chase`; dystraktor `point` bliski „get to the point”, możliwa niejednoznaczność). Miara: (a) trafność rozwiązywania przez Bielika z kluczem człowieka; (b) LT jako walidator zadania — wstaw każdą opcję w lukę i sprawdź, czy LT akceptuje klucz i odrzuca dystraktory (dotyczy zadań gramatycznych; dla reading/listening „nie dotyczy”). Wynik decyduje, czy `--solve-check` może dalej nadawać `ai_checked` (próg §5.4).

### 5.2 Systemy
- **A** – Bielik 11B, obecny prompt `turn_eval` (wersja zapisana), `classify()`.
- **B** – LanguageTool lokalnie, `lt_map` + `classify()`; bez Bielika.
- **C** – A + B przez `lt_merge` (§4.5).
Wszystkie wyniki przez te same walidatory deterministyczne; ten sam sprzęt; Bielik na GPU z offloadem jak w produkcji; Whisper niezaładowany (przypadki głosowe mają gotowe `words`).

### 5.3 Miary
| Miara | Definicja |
|---|---|
| precision | zgłoszenia liczone (`error`, p ∈ {h, m}) trafiające w span złoty (nakładanie ≥ 1 tokenu) / wszystkie zgłoszenia liczone; z przedziałem Wilsona 95% |
| recall | trafione spany złote / wszystkie spany złote (E1+E2) |
| FPR | zdania z C1+C2+C3+S+D z ≥ 1 zgłoszeniem liczonym / liczba tych zdań; osobno per podzbiór |
| poprawność korekty | trafienia, w których zdanie po poprawce ∈ `fix_accept` (normalizacja wielkości liter, interpunkcji, kontrakcji) / trafienia |
| zachowanie znaczenia | ocena człowieka 0/1 na zdaniu po poprawce względem `meaning`; automatyczny strażnik: poprawka zmieniająca > 50% tokenów = podejrzana |
| poprawność wyjaśnienia | kategoria zgodna ze złotą (rdzeń taksonomii) → szablon PL z `errors.yaml` poprawny; człowiek ocenia 1–5 próbkę 20 wyjaśnień (z szablonu i z LLM, gdy szablonu brak) |
| akceptacja BrE/AmE | 1 − FPR na C2 |
| zachowanie wobec STT | odsetek przypadków S z 0 zgłoszeń liczonych (`stt_suspect` dozwolone) |
| opóźnienie | p50/p95 na wypowiedź: LT, TurnEval, całość kolejki |
| zasoby | szczyt RSS procesu Javy i Ollamy (`/proc/<pid>/status`), VRAM (`nvidia-smi`), CPU % (czas CPU / czas ścienny z `/proc/<pid>/stat`) |
| wpływ na rozmowę | TTFT rozmowy Bielika z LT bezczynnym vs tuż po sprawdzeniu (sekwencyjnie, jak w kolejce) |

Wyniki per podzbiór i per kategoria taksonomii (do bramy per kategoria). Raport: `docs/ai-work/BENCHMARK_GRAMMAR.md` (lub sekcja w `BENCHMARK.md` z F8).

### 5.4 Kryteria dopuszczenia automatycznych korekt (mierzalne)
Konfiguracja (A, B lub C) jest **dopuszczona**, gdy na przypadkach `human_reviewed` (n ≥ 100, w tym ≥ 50 spanów złotych):
1. precision ≥ 0,80 **i** dolna granica Wilsona 95% ≥ 0,70;
2. FPR na C1+C2+C3 < 10%, a na C2 (BrE/AmE) < 10% osobno;
3. przypadki S: ≥ 95% bez zgłoszeń liczonych; D: 100% bez zgłoszeń liczonych dla wypełniaczy i powtórzeń;
4. poprawność korekty ≥ 0,85 trafień; zachowanie znaczenia ≥ 0,95;
5. kategoria wyjaśnienia zgodna ≥ 0,85; średnia oceny człowieka ≥ 4/5;
6. opóźnienie kolejki p95 ≤ 6 s (`periodic`), ≤ 10 s (`intensive`, istniejący twardy limit); LT p95 ≤ 300 ms; RSS LT ≤ 1 GiB; TTFT rozmowy pogorszone ≤ 5%.
Dodatkowo **per kategoria**: kategoria zasila `error_log`/BKT tylko, gdy jej precision ≥ 0,85 przy ≥ 8 zgłoszeniach (`quality_gate.trusted_categories`). Reguła LT trafia do `lt_trusted_rules` przy precision ≥ 0,90 i ≥ 5 zgłoszeniach.
Sędzia zadań (F3-11 + próbka 20 zadań `ai_checked` zrecenzowanych przez człowieka): `--solve-check` może nadawać `ai_checked` tylko przy zgodności z kluczem człowieka ≥ 0,90; inaczej wynik kontroli na ślepo to tylko notatka, status zostaje `draft`. Do czasu tego pomiaru obowiązuje zachowanie F3 z notatką „sędzia niezwalidowany” (§8 pkt 5).

### 5.5 Gdy jakość niewystarczająca (stan domyślny do czasu benchmarku)
- `quality_gate.bielik_benchmark_passed: false` (jest), `trusted_categories: []`, `lt_trusted_rules: []`.
- Korekty z rozmowy są **sugestiami** (`effective_style.suggestion_wording`, jest w F4).
- **Zmiana zachowania F4 (§8):** obserwacje z rozmowy z kategorii spoza `trusted_categories` **nie obniżają BKT** (brak aktualizacji „niepoprawna”) i nie resetują statusów. Trafiają do `observation` i `error_log` (rejestr błędów i zadania naprawcze działają — to tylko ćwiczenia), ale mastery zmieniają wyłącznie: zadania zamknięte (ocena deterministyczna), testy trwałości i użycia konstrukcji celu potwierdzone deterministycznie (wzorzec `target_patterns`/dopasowanie `fix`). Implementacja: jeden warunek w `tutor/app/ingest.py` (miejsce aktualizacji BKT z rozmowy), parametr z `rubric.yaml`; bez przebudowy silnika.
- Brama diagnozy CEFR (T-CONTENT-2: ≥ 15 `human_reviewed` na obszar × poziom) **bez zmian**; benchmark jej nie otwiera.

## 6. Ograniczenia (powtórzone, wiążące dla F4.6)
Bielik 11B domyślny; Gemini odroczony; prototyp głosowy działa bez zmian (`tests/test_voice_*` zielone); bez RAG, agentów, baz wektorowych; do LLM tylko pojedyncze fragmenty ≤ 1500 tokenów; PDF-y, EPUB-y, ekstrakty i dane uczniów poza Git (`.gitignore` + kontrola przed commitem); bez przebudowy F4 (dozwolone: nowe moduły `vocab.py`, `lt_merge.py`, warunek bramy w `ingest.py`, rozszerzenia schematu §2.1, migracja 004 tylko `ADD COLUMN`); LanguageTool opcjonalny, wyłączony domyślnie, aplikacja działa bez niego.

## 7. Ryzyka
| Ryzyko | Środek |
|---|---|
| Brehe: licencja tylko w PDF, strona UNG milczy; włączone treści ND | tylko tekst autora, parafraza, `license: CC-BY-SA-4.0`, `refs` do strony; wyjaśnienia z innych źródeł mają pierwszeństwo, gdy równoważne |
| ShareAlike „zaraża” pliki mieszane | osobne pliki/zadania dla treści z `brehe`/`ngsl`; walidator licencji |
| Repo bez `LICENSE` | decyzja użytkownika (§1.3) |
| Definicje NGSL jednoznaczne, homografy | flaga `homograph`, definicje tylko pomocnicze, glosy PL `draft` |
| Brak rang w lokalnych plikach | pobranie `NGSL_12_stats.csv`; bez niego `rank` puste i test rozpoznawania oznaczony jako przybliżenie |
| LT: parametry/RAM niezweryfikowane | test kontraktu na prawdziwej odpowiedzi, pomiar w C4/C5 przed włączeniem |
| LT zabiera CPU Bielikowi (offload) | tylko w kolejce oceny, sekwencyjnie, `nice`, 1 wątek; pomiar TTFT |
| Złoty standard pisany przez AI | liczy się tylko po recenzji człowieka; bez niej benchmark = „wstępny”, bramy się nie otwierają |
| Mała próba (n=130) | przedziały Wilsona; brama na dolnej granicy |

## 8. Zmiany decyzji (do HANDOFF / REQUIREMENTS)
1. Treść adaptowana ze źródeł otwartych: `provenance.source=ai_adapted`, `refs`, `license`; ShareAlike respektowany per plik (nowe RQ-3.14).
2. Słownictwo: NGSL 1.2 (+ NGSL-Spoken) jako lista bazowa; `cefr` słowa nigdy z częstości; brak masowych kart; wiedza bierna/czynna (nowe RQ-3.15).
3. LanguageTool: opcjonalny, wyłącznie localhost, wyłączony domyślnie, nie jest źródłem prawdy (nowe RQ-6.7).
4. **Do czasu bramy jakości obserwacje z rozmowy nie obniżają mastery** (zmiana względem F4, gdzie obserwacje h/m aktualizowały BKT) (nowe RQ-3.16).
5. Brama `ai_checked`: kontrola na ślepo nadaje `ai_checked` tylko po wykazaniu zgodności sędziego ≥ 0,90 (§5.4); do tego czasu nowe zadania F4.6 mogą dostać `ai_checked` jak w F3, ale z notatką „sędzia niezwalidowany”.
