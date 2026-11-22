# Moduł 03 – Naturalna konwersacja głosowa: raport

Gałąź `feat/voice-prototype` (z `feat/f0-scaffold`, commit 9d78646). Zakres: STT, TTS, prototyp CLI, benchmark. Bez silnika dydaktycznego i GUI. Bez wywołań zewnętrznych API (Gemini odroczony; tryb głosowy odrzuca dostawców `external`).

## Uruchomienie
Środowisko: `.venv` (Python 3.12). Zależności: `pip install -r requirements.txt` (sekcja głosowa: numpy, sounddevice, faster-whisper, kokoro-onnx, piper-tts, onnxruntime; **bez torcha**, CPU).

1. **PortAudio** (sounddevice go nie wbudowuje na Linuksie): `sudo apt install libportaudio2`. Bez sudo: `apt download libportaudio2 && dpkg-deb -x libportaudio2*.deb x && mkdir -p ~/.local/lib/english-ai-tutor && cp x/usr/lib/x86_64-linux-gnu/libportaudio.so.2.0.0 ~/.local/lib/english-ai-tutor/libportaudio.so.2` (kod sam go wtedy znajduje; tak jest zrobione na tej maszynie).
2. **Modele** (poza repozytorium, `~/.local/share/english-ai-tutor/models/`, ≈470 MB):
   - Kokoro: `kokoro/kokoro-v1.0.int8.onnx` + `kokoro/voices-v1.0.bin` z github.com/thewh1teagle/kokoro-onnx/releases (model-files-v1.0).
   - Piper: `cd ~/.local/share/english-ai-tutor/models/piper && python -m piper.download_voices en_GB-alba-medium en_GB-jenny_dioco-medium en_US-lessac-medium en_US-amy-medium en_US-ryan-high`.
   - Whisper: pobierany automatycznie przy pierwszym użyciu do cache HF (`small.en`, opcjonalnie `base.en`).
3. `ollama serve` (Bielik 11B Q4_K_M jest domyślnym modelem roli `conversation`), profil: `python main.py profile create NAZWA`.
4. `python main.py --voice [opcje]`

| Opcja | Znaczenie |
|---|---|
| `--mode ptt` (domyślny) | Enter = start nagrywania, Enter = stop. Enter w trakcie mowy tutora = przerwanie mowy i generowania |
| `--mode auto` | eksperymentalnie: bez przycisku, detekcja końca wypowiedzi; mikrofon wyciszony, gdy tutor mówi (half-duplex) |
| `--tts kokoro\|piper`, `--tts-voice`, `--speed` | silnik i głos (np. `bf_emma`, `am_michael`, `en_US-lessac-medium`) |
| `--stt-model small.en\|base.en\|small\|…`, `--language` | inne języki: `--stt-model small --language de` (model wielojęzyczny) |
| `--input-device`, `--output-device`, `--list-devices` | wybór urządzeń |
| `--no-audio` | tekst → tekst (bez mikrofonu/głośnika) |

Wpisany tekst + Enter wysyła wypowiedź tekstowo (to samo przejście, co po STT). `q` = wyjście. Brak mikrofonu/PortAudio → komunikat i tryb tekstowy z mową tutora. Domyślne wartości w `config.toml`, sekcja `[voice]`: `mode, tts, tts_voice, speed, stt_model, language, input_device, output_device`.

## Architektura (`tutor/voice/`)
- `audio.py` – `Mic` (sounddevice, 16 kHz, `mute()`), `Endpointer` (energia + adaptacyjny próg szumu, kalibracja 0,3 s, odrzucanie krótkich impulsów, limit 30 s, ucięcie ciszy końcowej), `Speaker` (strumień wyjściowy, `stop()` kasuje bufor, licznik niedomiarów), `SimSink` (zegar odtwarzania do testów/benchmarku).
- `stt.py` – `WhisperSTT` (faster-whisper, CPU int8, 8 wątków, beam 1, filtr VAD, odrzucanie segmentów „no speech” i typowych halucynacji na ciszy). Interfejs: `transcribe(audio) -> str`.
- `tts.py` – wymienny interfejs `TTS.synth(text) -> float32`, `KokoroTTS`, `PiperTTS`, `build_tts`.
- `text.py` – `SentenceSplitter` (zdanie dopiero po znaku końca + spacji; nie tnie „Dr.”, „3.5”, inicjałów; pierwszy fragment może skończyć się przecinkiem po ≥40 znakach), `clean_for_speech` (markdown/emoji).
- `conversation.py` – `VoiceTutor.respond()`: pamięć i limity przez istniejące `build_context`, strumień Bielika → zdania → wątek syntezy → głośnik; `cancel()` zatrzymuje LLM (zamyka połączenie), syntezę i głośnik. W bazie ląduje tylko tekst **faktycznie wypowiedziany**. Checkpoint pamięci co 10 wpisów jest ekstrakcyjny (bez wywołania LLM, żeby nie dodawać sekund do tury).
- `cli.py` – pętla `--voice`. Nagrania nigdy nie trafiają na dysk (tylko RAM; test sprawdza brak plików).
- **Echo własnego głosu:** mikrofon odrzuca dźwięk (`mute`) od startu odpowiedzi do 0,4 s po jej końcu; w trybie ptt nagrywanie i tak zaczyna się dopiero po Enter. Konsekwencja: w trybie auto nie ma przerywania głosem (barge-in) – tylko Enter. Zalecane słuchawki; z głośnikami echo nie jest testowane fizycznie.
- Nie oceniamy wymowy: STT daje tekst; system prompt zakazuje komentowania wymowy, nic w kodzie jej nie ocenia.

## Porównanie TTS (lokalnie, CPU)
Próbki: `~/.local/share/english-ai-tutor/voice_samples/*.wav` (poza repozytorium – licencje głosów; 44 pliki = 11 głosów × 4 identyczne teksty, `metrics.json`). Generator: `PYTHONPATH=. .venv/bin/python tests/live/tts_samples.py`. Teksty: 1 powitanie/pytania, 2 daty i liczby („Wednesday”, „thorough”, „twelve pounds fifty”), 3 korekta z przecinkami, 4 trudne słowa („schedule”, „February”, „I'd rather”).

**Naturalności intonacji i poprawności wymowy nie oceniłem – nie słucham dźwięku. To czeka na Twoje ucho** (kolejność odsłuchu: `bf_emma` ↔ `en_GB-alba-medium`, `af_heart` ↔ `en_US-lessac-medium`, potem reszta; porównuj ten sam numer tekstu). Poniżej wyłącznie pomiary obiektywne (średnia z 4 tekstów; RTF = czas syntezy / czas dźwięku; „start” = synteza pierwszej frazy; tempo = słów/s, im większa suma pauz wewnętrznych ≥150 ms, tym więcej „oddechu”; poza ~2,5–3,5 słów/s mowa brzmi zwykle za wolno/szybko):

| Silnik / głos | wariant | RTF | start 1. frazy | tempo sł/s | pauzy Σ | licencja głosu |
|---|---|---|---|---|---|---|
| Kokoro `bf_emma` | BrE | 0,32 | 0,44 s | 3,68 | 0,64 s | Apache-2.0 |
| Kokoro `bf_isabella` | BrE | 0,32 | 0,47 s | 3,62 | 0,68 s | Apache-2.0 |
| Kokoro `bm_george` | BrE m | 0,31 | 0,49 s | 3,07 | 0,96 s | Apache-2.0 |
| Kokoro `af_heart` | AmE | 0,31 | 0,43 s | 3,36 | 0,86 s | Apache-2.0 |
| Kokoro `af_bella` | AmE | 0,33 | 0,43 s | 3,22 | 1,07 s | Apache-2.0 |
| Kokoro `am_michael` | AmE m | 0,33 | 0,45 s | 2,97 | 1,15 s | Apache-2.0 |
| Piper `en_GB-alba-medium` | BrE | 0,046 | 0,07 s | 2,97 | 1,36 s | CC BY 4.0 (atrybucja) |
| Piper `en_GB-jenny_dioco-medium` | BrE | 0,043 | 0,05 s | 3,52 | 0,53 s | licencja zbioru Jenny – sprawdź przed dystrybucją |
| Piper `en_US-lessac-medium` | AmE | 0,050 | 0,06 s | 3,17 | 0,93 s | Blizzard 2013 (Lessac) – warunki zbioru |
| Piper `en_US-amy-medium` | AmE | 0,040 | 0,08 s | 2,54 | 1,19 s | „See URL” w karcie – niejednoznaczna, sprawdź |
| Piper `en_US-ryan-high` | AmE m | 0,178 | 0,19 s | 4,03 | 0,14 s | **CC BY-NC-SA 4.0 (tylko niekomercyjnie)** |

Zasoby: Kokoro int8 ≈ 92 MB model + 28 MB głosy, ~4 wątki CPU, RSS aplikacji z Whisperem ≈ 1,2 GB; Piper medium ≈ 63 MB / głos (high 121 MB), RSS ≈ 1,1 GB. Żaden nie używa GPU (VRAM bez zmian ≈ 7,0 GiB, zajęte przez Bielika).
Licencje silników: Kokoro-82M (model) Apache-2.0, `kokoro-onnx` MIT; **`piper-tts` 1.8 jest GPL-3.0-or-later**; oba używają fonemizatora espeak-ng (GPL-3.0, ładowany jako biblioteka). Do użytku osobistego bez znaczenia, przy dystrybucji aplikacji – tak. Faster-whisper, CTranslate2, wagi Whispera: MIT.

Wniosek techniczny (nie wybór zwycięzcy): Piper startuje ~6× szybciej i prawie nie obciąża CPU; Kokoro jest 7× wolniejszy w syntezie, ale wciąż szybszy niż mowa (RTF 0,32) i ma jedną licencję. Decyzja o głosie należy do Ciebie po odsłuchu. Kod trzyma oba za jednym interfejsem; `--tts`/`--tts-voice` lub `[voice]` w `config.toml`.

## Benchmark (live, 22 tury, Bielik 11B Q4_K_M z offloadem CPU, Ryzen 7 3700X, RTX 2060 SUPER)
Skrypt: `PYTHONPATH=. .venv/bin/python tests/live/bench_voice.py --tts piper --stt-model small.en --json out.json`. Uczeń = syntetyczny głos Piper `lessac` (inny niż tutor), przepuszczony przez prawdziwy `Endpointer` i Whisper; LLM i TTS prawdziwe; **odtwarzanie jest symulowane zegarem** (bez dźwięku z głośnika), więc „pierwszy słyszalny fragment” = moment oddania pierwszych próbek do głośnika (rzeczywiste opóźnienie bufora ALSA/PipeWire ~20–50 ms dochodzi). Czas liczony od końca nagrania (decyzji Endpointera); sam Endpointer czeka ponadto 0,7 s ciszy, którą trzeba doliczyć do odczuwanego opóźnienia.

| Konfiguracja | mediana → 1. dźwięk | p90 | min–max | STT (med.) | 1. token od końca | 1. zdanie gotowe | cel < 3 s |
|---|---|---|---|---|---|---|---|
| Piper + `small.en` | **2,64 s** | 3,41 | 2,04–5,06 | 1,53 | 1,89 | 2,43 | tak |
| **Kokoro + `small.en`** | **3,44 s** | 5,70 | 2,83–6,97 | 1,46 | 1,80 | 2,35 | **nie** |
| Piper + `base.en` | **1,65 s** | 3,52 | 1,38–3,82 | 0,56 | 0,91 | 1,51 | tak |
| Kokoro + `base.en` | **2,70 s** | 4,15 | 2,01–6,34 | 0,56 | 0,91 | 1,47 | tak |

Pozostałe pomiary (22 tury każda konfiguracja): 0 błędów, 4 checkpointy pamięci, kontekst w limicie; VRAM szczyt ≈ 7,0 GiB z 8 (Bielik; baza pulpitu 0,6 GiB), RAM: aplikacja 0,8–1,2 GiB (szczyt, z Whisperem i TTS), Ollama ≈ 7,5 GiB. Transkrypcja czystej mowy syntetycznej zgodna co do słowa (po normalizacji wielkości liter i interpunkcji) w 16–17/22 tur dla `small.en` i 12–14/22 dla `base.en` (np. „Jacek” → „Chasek” w `base.en`) – to próba z syntetycznym, czystym głosem, nie z Twoim akcentem; realny WER sprawdzi odsłuch na żywo.

**Płynność odtwarzania:** w 5–12 z 22 tur wystąpiła przerwa między zdaniami (łącznie 2,4–17 s na 22 tury; najczęściej 0,2–0,7 s, pojedyncze dłuższe). Przyczyna: Bielik 11B generuje ~11 tok/s, a pierwszy fragment bywa krótki (~1 s mowy), więc kolejne zdanie nie zdąża. Kokoro ma więcej przerw (7–12 tur) niż Piper (5 tur) – dochodzi jego czas syntezy.

**Gdzie ucieka czas (Kokoro + small.en, mediana 3,44 s):** STT 1,5 s (Whisper `small` koduje zawsze okno 30 s – czas prawie nie zależy od długości wypowiedzi ani liczby wątków: 4/8 wątków dały to samo ≈1,6 s) · 1. token Bielika ≈ +0,35 s · reszta pierwszego zdania ≈ +0,55 s · synteza 1. zdania Kokoro ≈ +0,5–1,0 s.

**Optymalizacje (od najtańszej):**
1. `--tts piper` (−0,8 s) albo `--stt-model base.en` (−0,9 s; gorsza dokładność) – oba spełniają cel.
2. Potokowa transkrypcja: dekodować w trakcie mówienia (okna co ~2 s), a po końcu tylko ostatni fragment; usuwa większość z 1,5 s przy `small.en`. Wymaga nowego kodu (nie zrobione).
3. Bielik 7B (64 tok/s, cały na GPU, ~6 GiB VRAM): 1. zdanie po ~0,3 s i brak przerw, kosztem jakości odpowiedzi; Whisper dalej na CPU.
4. Bufor startowy: zacząć mówić dopiero, gdy pierwszy fragment ma ≥1,5 s dźwięku albo przewidywana przerwa jest krótka – mniej przerw kosztem +0,3–0,5 s startu (nie zrobione; parametr `first_clause` w `SentenceSplitter` już steruje długością pierwszej frazy).
5. Whisper na GPU (`int8_float16`, ~0,5–1 GiB) – mieści się tylko po zmniejszeniu Bielika lub kontekstu; niesprawdzone.
Nie stroiłem wątków ONNX Kokoro (4) ani nie mierzyłem `distil-small.en`.

## Testy
- Automatyczne (bez sprzętu, atrapy STT/TTS/mikrofonu): `.venv/bin/pytest` → **132 passed, 1 skipped, 11 deselected (live)**; `ruff check .` czysty. Nowe: `tests/test_voice_unit.py` (splitter, czyszczenie tekstu, Endpointer: koniec mowy, odrzucenie kliknięcia i ciszy, adaptacja do szumu tła, limit długości, `listen_auto`, zegar `SimSink`), `tests/test_voice_conversation.py` (potok zdań, start TTS przed końcem odpowiedzi LLM, anulowanie w trakcie generowania i po nim kolejna tura, awaria LLM i TTS, brak zawieszenia, pamięć i limity kontekstu przez 25 tur, CLI: brak mikrofonu → tryb tekstowy, pusta transkrypcja, brak plików z nagraniami, wyciszenie mikrofonu po mowie, odrzucenie dostawcy zewnętrznego, brak Ollamy, Enter przerywa mowę, kolejność wpisanych linii). Regresja F0–F2 bez zmian.
- Live (`pytest -m live tests/live/test_live_voice.py`): **6 passed** – oba silniki TTS tworzą mowę, Whisper rozpoznaje zdanie z mowy syntetycznej, cisza/szum → pusty tekst, **prawdziwy mikrofon (mikrofon kamery Live! Cam Sync HD, ALSA) przechwytuje ~33 bloków/s** (szum otoczenia: mediana RMS 0,003, szczyt 0,016; próg detekcji ≥0,01 przez ≥3 ramki), głośnik otwiera się i jest zatrzymywany.
- Live smoke: `python main.py --voice --no-audio --tts piper` z prawdziwym Bielikiem i Piperem (2 tury, start mowy ≈1 s).
- Poprawki wykryte testami: próg Endpointera na starcie w hałasie, kolejność wpisanych linii podczas mowy, błąd LLM nie wycina już zakolejkowanych zdań.

## Do akceptacji użytkownika (wymaga fizycznej rozmowy)
1. Odsłuch próbek i wybór głosu/silnika (naturalność, intonacja, wymowa „Wednesday/February/schedule”).
2. `python main.py --voice`: rozmowa ≥20 tur głosem; czy Whisper rozumie Twój akcent (`small.en` vs `base.en`), czy tutor odpowiada naturalnie i krótko.
3. Przerwanie mowy Enterem w trakcie odpowiedzi; zachowanie po przerwaniu.
4. `--mode auto`: czy próg i 0,7 s ciszy pasują do pokoju; przy głośnikach (bez słuchawek) sprawdzić, czy tutor nie transkrybuje siebie (zabezpieczenie: wyciszenie mikrofonu + 0,4 s ogona; niezweryfikowane fizycznie).
5. Realne opóźnienie od Twojego ostatniego słowa do głosu (≈ pomiar + 0,7 s ciszy końcowej + bufor audio).
6. Decyzje: domyślny TTS (Kokoro przekracza 3 s medianą z `small.en`), BrE czy AmE, czy zapisywać nagrania (obecnie nigdy).

## Ograniczenia
- Whisper `small.en` i Kokoro/Piper konkurują o CPU z warstwami Bielika w RAM; pomiary dotyczą tej maszyny i modelu 11B.
- Brak przerywania głosem (barge-in) i brak ewaluacji wymowy (poza zakresem).
- Checkpoint pamięci ekstrakcyjny, nie LLM (jakość niższa, ale 0 ms).
- Pomiar odtwarzania symulowany; płynność na prawdziwym głośniku do potwierdzenia na żywo.
- `sounddevice` emituje ostrzeżenie deprecjacji NumPy 2.5 (nieszkodliwe).
