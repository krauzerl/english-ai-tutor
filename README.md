# English AI Tutor

Lokalny tutor AI do nauki języka angielskiego, działający z wykorzystaniem Ollamy.

## Aktualne funkcje

- rozmowa tekstowa z lokalnym modelem,
- historia rozmowy podczas jednej sesji,
- podstawowy prompt nauczyciela angielskiego,
- lokalne działanie bez wysyłania rozmów do zewnętrznych API.

## Technologie

- Python 3.12
- Ollama
- Requests

## Uruchomienie

1. Aktywuj środowisko:

```bash
source .venv/bin/activate
```

2. Zainstaluj zależności:

```bash
pip install -r requirements.txt
```

3. Sprawdź dostępne modele Ollamy:

```bash
ollama list
```

4. Uruchom aplikację:

```bash
python main.py
```

## Plan rozwoju

- rozpoznawanie mowy,
- odpowiedzi głosowe,
- aplikacja desktopowa,
- zapis historii i postępów,
- system powtórek i analizy błędów.