# Propozycja podziału licencji (F4.6) — DO POTWIERDZENIA

**Status: projekt.** Nie dodano pliku `LICENSE`, `tutor/content/LICENSE.md` ani żadnej innej deklaracji licencyjnej.
Zgodnie z decyzją użytkownika ostateczne nadanie licencji kodu wymaga jego potwierdzenia. To nie jest porada prawna.

## 1. Rekomendowany podział

| Część repozytorium | Rekomendowana licencja | Uzasadnienie |
|---|---|---|
| Własny kod: `tutor/` (poza `tutor/content/`), `tools/`, `bench/*.py`, `tests/`, `main.py` | **MIT** | Permisywna, zgodna z zależnościami (MIT/Apache/BSD). Wymaga wskazania właściciela praw autorskich. |
| Treści: `tutor/content/**` (YAML, MD, CSV), `bench/cases/**` | **CC BY-SA 4.0** | `vocab/ngsl.csv` i adaptacje z Brehe's Grammar Anatomy są utworami zależnymi od CC BY-SA 4.0 (ShareAlike). Jedna licencja dla całego katalogu treści jest prostsza niż mieszanie; adaptacje z CC BY (ESOL, Green Tea, TWE) wolno wydać na CC BY-SA 4.0. Wyjątki per plik pozostają w polu `license`. |
| Atrybucje źródeł | `tutor/content/en/ATTRIBUTION.md` (generowany z `sources.yaml`) | Wymóg CC (autor, źródło, licencja, informacja o zmianach). |
| Zależności i modele | **nie relicencjonowane** — osobne informacje (sekcja 2) | Zachowują własne licencje; modele nie są w repozytorium. |

Kod i treść są oddzielnymi utworami: licencja ShareAlike treści nie przechodzi na kod (kod tylko czyta pliki treści w czasie działania).
Rekomendacja pozostaje ważna tylko przy założeniu, że repozytorium nie dystrybuuje źródeł (PDF/EPUB/XHTML/ekstrakty są w `.gitignore`).

## 2. Zależności i modele (stan zweryfikowany 2026-11-22)

| Składnik | Licencja | Źródło informacji | Uwaga |
|---|---|---|---|
| pydantic, PyYAML, fsrs, sounddevice, faster-whisper, onnxruntime | MIT | metadane zainstalowanych pakietów | |
| requests, google-genai | Apache-2.0 | metadane pakietów | Gemini odroczony (opcjonalny) |
| numpy | BSD-3-Clause (+ 0BSD, MIT, Zlib, CC0) | metadane | |
| kokoro-onnx | w metadanych puste; wg wcześniejszej notatki w `pyproject.toml` MIT/Apache-2.0 | **do zweryfikowania** w repozytorium projektu | opcjonalna (`voice`) |
| **piper-tts** | **GPL-3.0-or-later** | metadane pakietu | **opcjonalna** zależność `voice`. Importowana tylko w module głosowym; nie wolno jej dołączać do dystrybucji kodu MIT jako zależności obowiązkowej ani wysyłać razem w jednym pakiecie bez analizy GPL. Zalecenie: zostawić opcjonalną, nie pakować, albo usunąć i zostać przy Kokoro. |
| Bielik 11B v2.3 Instruct (domyślny model) | Apache-2.0 | karta modelu na Hugging Face (API) | model pobierany lokalnie przez Ollamę, nie w repo |
| Kokoro-82M | Apache-2.0 | karta HF | |
| faster-whisper `small.en` | MIT | karta HF | |
| Głosy Piper | MIT wg karty repozytorium `rhasspy/piper-voices`; **poszczególne głosy mają własne licencje** | karta HF | sprawdzić licencję konkretnego głosu przed użyciem |
| LanguageTool 6.6 | LGPL-2.1-or-later | `COPYING.txt` w paczce | uruchamiany jako **osobny proces lokalny**, nie linkowany i nie dołączany do repo |
| NGSL / NGSL-Spoken 1.2 | CC BY-SA 4.0 | strona NGSL | `SUP_lemmatized.csv` pominięty (pochodzenie niepotwierdzone) |
| ESOL / Green Tea / TWE | CC BY 4.0 z wyjątkami | strony redakcyjne | wyjątki TWE (S.1, ryciny) wykluczone w `sources.yaml` |
| Brehe's Grammar Anatomy | CC BY-SA 4.0 **wg strony redakcyjnej PDF** | PDF (strona UNG licencji nie podaje) | najsłabiej udokumentowana licencja; użyty tylko tekst autora jako podstawa parafraz |

## 3. Pliki, które powstaną po potwierdzeniu

1. `LICENSE` — tekst MIT z imieniem właściciela praw (**potrzebne: kto jest właścicielem i jaki rok**).
2. `tutor/content/LICENSE.md` — CC BY-SA 4.0 (wskazanie + link do legalcode) z odesłaniem do `ATTRIBUTION.md`.
3. `THIRD_PARTY_NOTICES.md` — tabela z sekcji 2 (po weryfikacji kokoro-onnx i głosu Piper).
4. Sekcja „Licencje” w `README.md`.
5. Pole `license` w `pyproject.toml`.

## 4. Decyzje wymagane od użytkownika

1. Czy potwierdzasz **MIT** dla kodu? Kto jest właścicielem praw i jaki rok wpisać?
2. Czy cały `tutor/content/` i `bench/cases/` ma być na **CC BY-SA 4.0**?
3. Co z **piper-tts (GPL-3.0)**: zostawić jako opcjonalną zależność czy usunąć z `pyproject.toml`?
4. Czy akceptujesz oparcie licencji Brehe wyłącznie na nocie w PDF (bez potwierdzenia na stronie UNG)?
