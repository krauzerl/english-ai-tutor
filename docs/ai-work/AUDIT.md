# AUDIT – stan faktyczny (2026-11-22)

## 1. Repozytorium
| Plik | Linie | Stan |
|---|---|---|
| `main.py` | 40 | Pętla CLI: `input()` → POST `/api/chat` Ollamy → `print`. |
| `ollama_client.py` | 0 | Pusty. |
| `prompts.py` | 0 | Pusty. |
| `requirements.txt` | 5 | Tylko `requests` + zależności przechodnie. |
| `README.md` | 49 | Opis CLI + plan rozwoju. |
| `.gitignore` | 4 | `.venv/ .idea/ __pycache__/ *.pyc .env` |

Historia: 2 commity (2026-07-20). Brak testów, CI, pakietu, konfiguracji, bazy danych, UI, audio.

## 2. Co rzeczywiście działa
- Rozmowa tekstowa w terminalu z modelem `SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M` — **pod warunkiem** uruchomionego `ollama serve`.
- Historia tylko w RAM w obrębie procesu.
- README twierdzi „lokalne działanie bez zewnętrznych API” — prawda.

Nie działa / nie istnieje: mowa (STT), TTS, GUI, SQLite, profil ucznia, diagnoza, powtórki, wielu użytkowników.

## 3. Błędy i dług techniczny w `main.py`
1. Brak obsługi `requests.ConnectionError`/`Timeout` — wyjątek kończy program, traci rozmowę.
2. `messages` rośnie bez limitu — przy długiej rozmowie przekroczy kontekst modelu (Bielik 11B v2.3: 32k tokenów) i spowolni każde zapytanie.
3. Model i URL zahardkodowane.
4. `KeyboardInterrupt`/`EOFError` (Ctrl+C/Ctrl+D) — traceback.
5. Brak `if __name__ == "__main__":` — nietestowalne.
6. Prompt systemowy ogólnikowy; brak poziomu, celów, formatu korekty.
7. Puste pliki `ollama_client.py`, `prompts.py` — martwe, zostaną wypełnione zgodnie z ARCHITECTURE.

Wniosek: kod do zachowania praktycznie tylko jako wzorzec wywołania `/api/chat`. To nie przebudowa „od zera” — projektu jeszcze nie ma; dokumenty opisują jego budowę na tym fundamencie.

## 4. Środowisko (zweryfikowane)
| Element | Stan |
|---|---|
| OS | Ubuntu 24.04.3 LTS |
| CPU | AMD Ryzen 7 3700X, 16 wątków |
| RAM | 31 GiB (24 GiB dostępne), swap 8 GiB |
| GPU | NVIDIA RTX 2060 SUPER, **8 GiB VRAM**, sterownik 580.178.04 |
| Dysk | 793 GB wolne |
| Python | system 3.13.5; `.venv` **3.12.3** (używane) |
| Ollama | klient **0.9.0** (stary), serwis `systemd` **disabled**, serwer nie działał podczas audytu |
| Modele Ollama | `bielik-11b-v2.3-instruct`, `bielik-7b-instruct-v0.1-gguf` (11 GB w `/usr/share/ollama`) |
| Whisper / faster-whisper | **brak** |
| Piper TTS | **brak** |
| ffmpeg | **brak** |
| PySide6 | **brak** |
| SQLite | moduł Python 3.45.3 (OK); CLI z anacondy |
| Audio | `arecord`, `pw-record` (PipeWire) dostępne |
| `GEMINI_API_KEY` | nieustawiony |

## 5. Budżet zasobów (szacunki do potwierdzenia benchmarkiem, faza F8)
| Komponent | VRAM | RAM |
|---|---|---|
| Bielik 11B Q4_K_M (~6.7 GB wag) + KV cache 8k | ~7.3 GB | – |
| Bielik 7B v0.1 Q4 | ~4.5 GB | – |
| faster-whisper `small` int8 | ~1 GB GPU lub CPU | ~1 GB |
| faster-whisper `medium` int8 | ~2 GB | ~2.5 GB |
| Piper (ONNX, CPU) | 0 | ~100 MB |
| PySide6 + app + SQLite | 0 | ~300 MB |

**Ryzyko krytyczne:** Bielik 11B + Whisper na GPU nie zmieszczą się razem w 8 GB. Decyzja: Whisper na **CPU** (int8, `small`; 3700X wystarcza do ~1–2× realtime) lub mniejszy LLM / Gemini dla trybu głosowego. Ograniczyć `num_ctx` do 8192.

Bielik 7B v0.1 jest przestarzały (słabe instrukcje) — kandydat do usunięcia po benchmarku.

## 6. Narzędzia Claude Code
| Narzędzie | Stan | Użycie |
|---|---|---|
| Ponytail | aktywny | audyt złożoności, minimalne zmiany |
| Superpowers | aktywny | `writing-plans`, `test-driven-development`, `subagent-driven-development`, `verification-before-completion` |
| Caveman | aktywny | zwięzłe odpowiedzi w czacie (nie w dokumentach) |
| Impeccable | **niedostępny** (brak pluginu/skilla) | zasady UI/UX spisane ręcznie w ARCHITECTURE §8 |
| Bezpieczeństwo | `claude-security` plugin, `/security-review` | uruchomić po F3 i przed udostępnieniem |

## 7. Ryzyka
| # | Ryzyko | Wpływ | Mitygacja |
|---|---|---|---|
| R1 | VRAM 8 GB | brak głosu przy 11B | Whisper CPU, `num_ctx` 8k |
| R2 | Jakość korekt Bielika po angielsku nieznana (model PL-centryczny) | błędne korekty uczą błędów | benchmark F8, walidacja reguł, Gemini jako alternatywa |
| R3 | LLM halucynuje poziom/CEFR | zły profil | silnik dydaktyczny deterministyczny; LLM tylko generuje i ocenia z rubryką, wynik walidowany |
| R4 | Ocena wymowy | ASR ≠ wymowa | osobny moduł; MVP tylko „zrozumiałość” z jawnym zastrzeżeniem |
| R5 | Limity/koszty Gemini | blokada lub koszt | licznik tokenów, limity dzienne, fallback do Ollamy |
| R6 | Dane innych osób | RODO | lokalnie, zgoda, eksport/usunięcie |
| R7 | Ollama 0.9.0 + serwis wyłączony | awarie startu | aktualizacja Ollamy, health-check w aplikacji |
| R8 | Brak bazy treści (banku zadań CEFR) | diagnoza niewiarygodna | własny bank zadań z metadanymi, ręcznie weryfikowany |
