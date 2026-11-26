# B-lite — rejestr eksperymentów (pre-rejestracja)

Zbiór: `bench/cases/control_b_lite.yaml` — SHA-256 `71cafcc26b4dd057db6cd2b559500c580479cb632cf2ec6c7d6025a6f914dc7e` (stan przed pierwszym uruchomieniem jakiegokolwiek
wariantu). Status: **NIEZWALIDOWANY** (autor: jedna osoba, model AI; brak recenzji człowieka). 123 przypadki:
dev 40 (25 błędów), held-out 83 (43 błędy).

Zasady:
1. Strojenie (polityka fuzji LT, lista zaufanych reguł, ewentualne reguły walidatorów) wyłącznie na `split=dev`
   oraz na starym `audit_control.yaml` (który już był oglądany w F7 i R&D — nie jest niezależny).
2. `split=held` uruchamiany raz, w końcowej bramce, dla wszystkich wariantów tym samym kodem. Wyniki held nie
   wracają do strojenia. Każde ponowne uruchomienie held po zmianie kodu oznaczane w tym pliku.
3. Zmiana pliku zbioru po pierwszym uruchomieniu = nowa wersja (nowa suma), z adnotacją dlaczego.
4. Wyniki z pojedynczego uruchomienia Ollamy nie są rozstrzygające: każdy wariant ≥ 3 powtórzenia, raport min–max.

Kryteria wstępne (brief B-lite §4): precision ≥ 90 %, brak istotnego wzrostu fałszywych korekt, recall wyższy od
baseline, brak istotnego pogorszenia czasu, stabilność przy braku/awarii LanguageTool.

## Dziennik uruchomień
(uzupełniany w kolejnych commitach)
- 2026-11-26 21:1x — `dev_AB.json` (A, B ×2, dev) i `audit_A.json` (A, stary zestaw). Ocena: pierwsza wersja
  `score` (jedno zgłoszenie = jeden błąd). Po obejrzeniu poprawiono `score`: jedno zgłoszenie może naprawić kilka
  oczekiwanych błędów (np. „works in a bank” = zgodność + przedimek). Zbioru NIE zmieniano (suma bez zmian).
- 2026-11-26 21:3x — `dev_ABCD.json`, `audit_ABCD.json`: A/B/C/D na dev i starym zestawie, LT 6.6 lokalnie;
  lista reguł-kandydatów `trust: h` w `lt_map.yaml` wybrana na podstawie surowych dopasowań LT na dev + audit
  (przed tym uruchomieniem).
