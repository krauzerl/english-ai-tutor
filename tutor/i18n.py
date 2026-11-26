"""Tłumaczenie komunikatów backendu na angielski interfejs (F7). Jedno miejsce dla tekstów, które silnik i API
pokazują uczniowi. Polski jest językiem źródłowym; brak tłumaczenia = tekst bez zmian (nigdy błąd).

Nie tłumaczymy wypowiedzi ucznia ani treści angielskich (tutor, zadania): `tr` zmienia wyłącznie teksty, które
pasują dokładnie do znanego komunikatu albo wzorca z parametrami.
"""
from __future__ import annotations

import re

EXACT = {
    "Brak celu lekcji z dostępnymi materiałami (wyjaśnienie i zadania).":
        "No lesson goal with available materials (explanation and tasks).",
    "Model oceny niedostępny lokalnie — oceny zostają w kolejce.":
        "The assessment model is not available locally — assessments stay in the queue.",
    "Ollama nie odpowiada: uruchom `ollama serve`.": "Ollama is not responding: run `ollama serve`.",
    "● nagrywam… (Enter = stop)": "● recording… (Enter = stop)",
    "Brak sugestii poprawek w ocenionych wypowiedziach.": "No correction suggestions in the assessed answers.",
    "Brak zaległych powtórek na dziś.": "No reviews due today.",
    "Czas rozmowy minął — kończymy.": "Time is up — we are finishing.",
    "Ćwiczenia przerwane — wznowisz je tym samym poleceniem.": "Practice paused — resume it with the same command.",
    "Diagnoza przerwana — wznowisz ją poleceniem `--assess`.": "Assessment paused — you can resume it later.",
    "Dopasowanie przerwane — wznowisz je poleceniem `--placement`.": "Placement paused — you can resume it later.",
    "Wszystkie wypowiedzi są ocenione.": "All answers have been assessed.",
    "Informacja zwrotna dotyczy wyłącznie języka, nie wiedzy ani decyzji klinicznych.":
        "Feedback is about language only, not clinical knowledge or decisions.",
    "Lekcja niedokończona — wróć do pominiętych zadań poleceniem `--lesson`.":
        "Lesson not finished — come back to the skipped tasks later.",
    "Lekcja przerwana — wznowisz ją przy następnym uruchomieniu z tym samym `--lesson`.":
        "Lesson paused — it will resume next time.",
    "(nagraj jeszcze raz)": "(record again)",
    "(nic nie zrozumiałem — spróbuj jeszcze raz)": "(I didn't catch anything — please try again)",
    "Profil kompetencji:": "Skill profile:",
    "Teraz krótka rozmowa po angielsku — użyj tego, co ćwiczysz (q = koniec).":
        "Now a short conversation in English — use what you practised.",
    "ocena wyłączona: model oceny niedostępny lokalnie; wypowiedzi zostaną ocenione później":
        "assessment off: the assessment model is not available locally; answers will be assessed later",
    "poprawiona transkrypcja — to nie jest błąd językowy": "corrected transcript — this is not a language error",
    "Powtórki przerwane — wznowisz je poleceniem `--review`.": "Reviews paused — you can resume them later.",
    "(słucham… mów; q = wyjście)": "(listening… speak)",
    "Brak zadań w tej ścieżce dla Twoich ustawień materiałów.": "No tasks in this path for your material settings.",
    "Dobrze, kończymy dopasowanie. Wynik będzie wstępny albo niepełny.":
        "OK, we stop the placement. The result will be preliminary or incomplete.",
    "Dobrze, kończymy na dziś. Lekcję możesz wznowić później.":
        "OK, that's all for today. You can resume the lesson later.",
    "Dzienny limit powtórek osiągnięty — reszta poczeka do jutra.":
        "Daily review limit reached — the rest will wait until tomorrow.",
    "Nie jestem pewien, czy dobrze usłyszałem. Powiedz jeszcze raz albo wpisz.":
        "I'm not sure I heard you correctly. Say it again or type it.",
    "Podczas ćwiczeń egzaminacyjnych nie ma podpowiedzi — odpowiedz najlepiej, jak potrafisz.":
        "There are no hints in exam practice — answer as well as you can.",
    "Przekładam tę powtórkę na jutro (bez wpływu na ocenę).":
        "Moving this review to tomorrow (no effect on your result).",
    "Do poprawy w tej rozmowie (to sugestie modelu — mogę się mylić):":
        "To improve in this conversation (model suggestions — I may be wrong):",
    "Dobrze, kończymy ćwiczenia. To nie oznacza opanowania umiejętności — nic nie zapisano jako zrobione. Do zadań "
    "wrócisz poleceniem `--lesson`.": "OK, we stop the practice. This does not mean the skill is mastered — nothing "
                                     "was saved as done. The tasks will wait for you.",
    "Pomijam to zadanie: rozpoznawanie mowy jest niepewne. Wpisz odpowiedź albo wróć do niego po wznowieniu lekcji.":
        "Skipping this task: speech recognition is uncertain. Type the answer or come back to it later.",
    "Sprawdzam odpowiedź…": "Checking your answer…",
    "Wynik to szacunek wstępny, nie diagnoza CEFR.": "The result is a preliminary estimate, not a CEFR assessment.",
    "to NIE są błędy ucznia — możliwe pomyłki rozpoznawania mowy":
        "these are NOT learner errors — possible speech recognition mistakes",
    "Osiągnięcia motywują; nie są oceną kompetencji.": "Achievements motivate; they are not a skill assessment.",
}

_P = [
    (r"^✓ Dobrze\.(?P<h> \(po podpowiedzi\))?(?P<rest>.*)$",
     lambda m: "✓ Correct." + (" (after a hint)" if m["h"] else "") + m["rest"]),
    (r"^Poprawna odpowiedź: (?P<a>.*)$", "Correct answer: {a}"),
    (r"^Nie jestem pewien, czy dobrze usłyszałem \(„(?P<t>.*)”\)\. Powiedz jeszcze raz albo wpisz( odpowiedź)?\.$",
     "I'm not sure I heard you correctly (“{t}”). Say it again or type it."),
    (r"^  Usłyszałem: „(?P<t>.*)”(?P<rest>.*)$", lambda m: f"  I heard: “{m['t']}”" + m["rest"]
     .replace(" (niepewne słowa: ", " (uncertain words: ").replace(" (brak danych o pewności rozpoznania)",
                                                                  " (no recognition confidence data)")),
    (r"^Wznawiam sesję #(?P<n>\d+)\.$", "Resuming session #{n}."),
    (r"^Wznawiam (?:ćwiczenia|powtórki|diagnozę|dopasowanie) \(sesja #(?P<n>\d+)\)\.$", "Resuming (session #{n})."),
    (r"^Quick Chat — temat: (?P<t>.*)\. \(Powiedz „change the topic”, by zmienić; q = koniec\.\)$",
     "Quick Chat — topic: {t}. (Say “change the topic” to change it.)"),
    (r"^nowy temat: (?P<t>.*)$", lambda m: "new topic: " + tr(m["t"], "en")),
    (r"^sprawdzam jeszcze (?P<n>\d+) wypowiedzi przed podsumowaniem…$",
     "checking {n} more answers before the summary…"),
    (r"^(?P<n>\d+) wypowiedzi oceni później: GUI \(Historia\) albo `--finish-evals`\.$",
     "{n} answers will be assessed later (Home → Finish assessing)."),
    (r"^Sprawdź rozpoznanie: „(?P<t>.*)”(?P<u>.*?) — Enter = wyślij · r = nagraj ponownie · wpisz poprawny tekst$",
     "Check the recognition: “{t}” — Enter = send · r = record again · type the correct text"),
    (r"^Oceniam (?P<a>\d+) wypowiedzi z (?P<b>\d+) rozmów…$", "Assessing {a} answers from {b} conversations…"),
    (r"^Ocenione: (?P<a>\d+), wciąż w kolejce: (?P<b>\d+)\.$", "Assessed: {a}, still queued: {b}."),
    (r"^Rozmowa #(?P<n>\d+):$", "Conversation #{n}:"),
    (r"^Ocena niekompletna: (?P<n>\d+) wypowiedzi czeka na sprawdzenie — (?P<rest>.*)$",
     "Assessment incomplete: {n} answers are waiting to be checked — the full summary will appear later."),
    (r"^Ustawienia rozmowy: (?P<s>.*)$", "Conversation settings: {s}"),
    (r"^Scenariusz: (?P<s>.*)$", "Scenario: {s}"),
    (r"^Koniec ćwiczeń: (?P<a>\d+)/(?P<b>\d+) poprawnych \(bez oceny: (?P<c>\d+)\)\. To nie jest wynik egzaminu\.$",
     "End of practice: {a}/{b} correct (not scored: {c}). This is not an exam result."),
    (r"^Powtórki: (?P<n>\d+) umiejętności do utrwalenia\. To sprawdza utrwalenie — nie nadaje opanowania\.$",
     "Reviews: {n} skills to consolidate. This checks retention — it never marks mastery."),
    (r"^Powtórki: (?P<a>\d+)/(?P<b>\d+) poprawnie\.(?P<rest>.*)$", "Reviews: {a}/{b} correct.{rest}"),
    (r"^Wynik ćwiczeń: (?P<a>\d+)/(?P<b>\d+) poprawnie\. .*$",
     "Practice score: {a}/{b} correct. This does not mean mastery — that needs confirmation on later days."),
    (r"^Przed tym rzeczownikiem potrzebny jest rodzajnik „(?P<x>.*)”\.$", "This noun needs the article “{x}”."),
    (r"^Tu rodzajnik „(?P<x>.*)” jest zbędny\.$", "The article “{x}” is not needed here."),
    (r"^Brakuje przyimka „(?P<x>.*)”\.$", "The preposition “{x}” is missing."),
    (r"^W tym wyrażeniu używamy przyimka „(?P<y>.*)”, nie „(?P<x>.*)”\.$", "This phrase takes “{y}”, not “{x}”."),
    (r"^Po he/she/it \(jedna osoba lub rzecz\) czasownik ma końcówkę -s: „(?P<y>.*)”, nie „(?P<x>.*)”\.$",
     "After he/she/it (one person or thing) the verb takes -s: “{y}”, not “{x}”."),
    (r"^Przy he/she/it \(jedna osoba lub rzecz\) mówimy „(?P<y>.*)”, nie „(?P<x>.*)”\.$",
     "With he/she/it (one person or thing) we say “{y}”, not “{x}”."),
    (r"^Przy tym podmiocie \(I/you/we/they lub liczba mnoga\) mówimy „(?P<y>.*)”, nie „(?P<x>.*)”\.$",
     "With this subject (I/you/we/they or plural) we say “{y}”, not “{x}”."),
    (r"^Przy tym podmiocie czasownik nie ma końcówki -s: „(?P<y>.*)”, nie „(?P<x>.*)”\.$",
     "With this subject the verb has no -s: “{y}”, not “{x}”."),
    (r"^To czasownik nieregularny: forma przeszła to „(?P<y>.*)”, nie „(?P<x>.*)”\.$",
     "This is an irregular verb: the past form is “{y}”, not “{x}”."),
    (r"^Z tym podmiotem mówimy „(?P<y>.*)”, nie „(?P<x>.*)”\.$", "With this subject we say “{y}”, not “{x}”."),
    (r"^Tu pasuje „(?P<y>.*?)”, nie „(?P<x>.*?)”\..*$", "“{y}” fits here, not “{x}”."),
    (r"^Naturalniej: „(?P<f>.*?)”\..*$", "More natural: “{f}”."),
    (r"^Poziom automatyczny: (?P<l>\w+)\. Nie ma jeszcze sprawdzenia poziomu.*$",
     "Automatic level: {l}. There is no level check yet, so I start carefully; you can choose a level manually."),
    (r"^Poziom automatyczny: (?P<l>\w+) \(z wyniku dobrowolnego sprawdzenia poziomu\)\.$",
     "Automatic level: {l} (from your optional level check)."),
    (r"^Wybór startowy: .*$", "Starting choice: the first goal with materials. This is not an assessment result."),
    (r"^wstępnie: (?P<x>.*)$", lambda m: "preliminary: " + _level_text(m["x"])),
    (r"^Nie sprawdzono: (?P<a>.*)\.$", lambda m: f"Not tested: {_area(m['a'])}."),
    (r"^Najniższy szacunek: (?P<a>\S+) \((?P<l>.*)\)\. Ćwicz cele z tego obszaru\.$",
     lambda m: f"Lowest estimate: {_area(m['a'])} ({tr(m['l'], 'en')}). Practise goals from this area."),
    (r"^Szeroki przedział niepewności: (?P<a>.*) — powtórz diagnozę tych obszarów, by go zawęzić\.$",
     lambda m: f"Wide uncertainty range: {', '.join(_area(x) for x in m['a'].split(', '))} — repeat the "
               "assessment of these areas to narrow it."),
    (r"^Szacunki wstępne z materiału niezweryfikowanego przez człowieka.*$",
     "Preliminary estimates from material not reviewed by a human — this is not an official CEFR level. The range "
     "shows uncertainty. Production (writing, speaking) has no validated rubric yet: we show evidence (amount, error "
     "suggestions), without a level."),
]
_PATTERNS = [(re.compile(p), r) for p, r in _P]
_AREAS = {"gramatyka": "grammar", "słownictwo": "vocabulary", "czytanie": "reading", "słuchanie": "listening",
          "mówienie": "speaking", "pisanie": "writing"}
_LEVEL_WORDS = [("prawdopodobnie", "probably"), ("przedział", "range"), ("środek", "centre"),
                ("lub wyżej", "or higher"), ("lub niżej", "or lower"),
                ("poniżej", "below"), ("powyżej", "above"), ("około", "about")]


def _area(a: str) -> str:
    return _AREAS.get(a, a)


def _level_text(x: str) -> str:
    for pl, en in _LEVEL_WORDS:
        x = x.replace(pl, en)
    return x


def tr(text: str, lang: str = "pl") -> str:
    """Tekst w języku interfejsu. `pl` (domyślnie) = bez zmian."""
    if lang != "en" or not isinstance(text, str) or not text:
        return text
    body = text.strip("\n")
    lead = text[:len(text) - len(text.lstrip("\n"))]
    if body in EXACT:
        return lead + EXACT[body]
    if " · " in body:                                    # „B1 · General English · Naturalna rozmowa”
        parts = [tr(x, lang) for x in body.split(" · ")]
        if parts != body.split(" · "):
            return lead + " · ".join(parts)
    head, sep, tail = body.partition(": ")              # „Nazwa sekcji: uwaga” sklejone w backendzie
    if sep and head in EXACT and (t := tr(tail, lang)) != tail:
        return lead + EXACT[head] + sep + t
    if body.startswith("[") and body.endswith("]"):
        return lead + "[" + tr(body[1:-1], lang) + "]"
    for pat, rep in _PATTERNS:
        m = pat.match(body)
        if m:
            return lead + (rep(m) if callable(rep) else rep.format(**m.groupdict()))
    return text


_TOPIC = "Quick Chat — temat: "


def _scenario_en(text: str) -> str:
    """Opis scenki z pól angielskich katalogu (`learner`, `role`); polski `context_pl` nie ma tłumaczenia."""
    from tutor.app import topics as T
    for it in T.chat_catalog("en")["items"].values():
        if it.get("context_pl") == text and it.get("learner") and it.get("role"):
            return f"You are {it['learner']}. The tutor plays {it['role']}."
    return text


def tr_event(ev: dict, lang: str) -> dict:
    """Zdarzenie sesji GUI: tłumaczymy pola tekstowe komunikatów, nigdy wypowiedzi ucznia ani tutora."""
    if lang != "en" or ev.get("kind") in ("you", "tutor", "heard", "stt_confirm", "task"):
        return ev
    text = ev.get("text") or ""
    if ev.get("kind") == "scenario":
        return {**ev, "text": _scenario_en(text)}
    if ev.get("kind") == "info" and text.startswith(_TOPIC):     # GUI czyta nazwę po polskim prefiksie
        name = text[len(_TOPIC):].split(". (")[0]
        return {**ev, "text": _TOPIC + tr(name, lang) + text[len(_TOPIC) + len(name):]}
    return {**ev, **{k: tr(v, lang) for k, v in ev.items() if k in ("text", "why") and isinstance(v, str)}}


def localize(obj, lang: str):
    """Odpowiedź API (JSON) w języku interfejsu: tłumaczy tylko znane komunikaty (`tr`), resztę zostawia."""
    if lang != "en":
        return obj
    if isinstance(obj, str):
        return tr(obj, lang)
    if isinstance(obj, list):
        return [localize(x, lang) for x in obj]
    if isinstance(obj, dict):
        return {k: localize(v, lang) for k, v in obj.items()}
    return obj


# Nazwy z katalogów treści (tematy Quick Chat, kategorie, tryby, egzamin). Klucz = tekst polski z YAML/kodu.
EXACT.update({
    "Dojrzałe rozmowy o codzienności, podróżach, planach i współczesnym świecie.":
        "Grown-up conversations about everyday life, travel, plans and the modern world.",
    "Programowanie, Python, AI, systemy, sieci, bezpieczeństwo, projektowanie aplikacji.":
        "Programming, Python, AI, systems, networks, security, application design.",
    "Język w ochronie zdrowia, szczególnie w ratownictwie medycznym. Ocena dotyczy języka, nie wiedzy klinicznej.":
        "Language for healthcare, especially emergency medical services. Feedback is about language, not clinical "
        "knowledge.",
    "Spotkania, negocjacje, prezentacje, startupy, inwestycje, zarządzanie projektami.":
        "Meetings, negotiations, presentations, start-ups, investment, project management.",
    "Rozmowa kwalifikacyjna, konferencja, prezentacja projektu, klient, telefon, problemy w pracy.":
        "Job interviews, conferences, project presentations, clients, phone calls, problems at work.",
    "Dowolny własny temat.": "Any topic of your own.",
    "Naturalna rozmowa": "Natural conversation", "Rozmowa prowadzona": "Guided conversation",
    "Praca a życie prywatne": "Work–life balance", "Podróż, którą pamiętasz": "A trip you remember",
    "Miejsce, w którym mieszkasz": "The place where you live", "Nowa umiejętność": "A new skill",
    "Wiadomości i media": "News and media", "Zdrowe nawyki": "Healthy habits",
    "Plany na najbliższy rok": "Plans for the coming year", "Książka albo film": "A book or a film",
    "Technologia na co dzień": "Everyday technology", "Zmiany w świecie pracy": "The changing world of work",
    "AI a zwykła praca": "AI and ordinary jobs", "Problem w hotelu": "A problem at the hotel",
    "Wynajem mieszkania": "Renting a flat", "Reklamacja w sklepie": "Returning a product",
    "Projekt w Pythonie": "A Python project", "Trudny błąd w kodzie": "A tricky bug",
    "Narzędzia AI w pracy": "AI tools at work", "System operacyjny": "Operating systems",
    "Co się dzieje, gdy otwierasz stronę": "What happens when you open a web page",
    "Cyberbezpieczeństwo": "Cybersecurity", "Projekt aplikacji": "Designing an app",
    "AI lokalnie czy w chmurze": "Local or cloud AI", "Rozmowa techniczna": "Technical interview",
    "Zgłoszenie do helpdesku": "A helpdesk ticket", "Klient zamawia aplikację": "A client orders an app",
    "Dyżur w zespole ratownictwa": "A shift in an ambulance crew", "Najczęstsze wezwania": "The most common calls",
    "Sprzęt w karetce": "Ambulance equipment", "Komunikacja w zespole": "Team communication",
    "Dobre przekazanie pacjenta": "A good patient handover", "Stres po trudnym wezwaniu": "Stress after a hard call",
    "Ból w klatce piersiowej": "Chest pain", "Duszność": "Shortness of breath",
    "Uraz po upadku z roweru": "Injury after a bike fall", "Wywiad z pacjentem (ból brzucha)":
        "Taking a history (abdominal pain)",
    "Przekazanie pacjenta na SOR": "Handover at the emergency department", "Rozmowa z rodziną pacjenta":
        "Talking to the patient's family",
    "Plan działań w zespole": "Planning as a crew", "Prezentacja przypadku": "Presenting a case",
    "Spotkania": "Meetings", "Twoja firma": "Your company", "Dzień w pracy": "A day at work",
    "Negocjacje": "Negotiations", "Pomysł na startup": "A start-up idea", "Inwestowanie w firmy":
        "Investing in companies",
    "Współpraca międzynarodowa": "International cooperation", "Zarządzanie projektem": "Project management",
    "Prezentacje biznesowe": "Business presentations", "Rozmowa z inwestorem": "Meeting an investor",
    "Negocjacja z dostawcą": "Negotiating with a supplier", "Opóźniony projekt i niezadowolony klient":
        "A delayed project and an unhappy client",
    "Nowy partner zagraniczny": "A new foreign partner", "Doświadczenie zawodowe": "Work experience",
    "Informacja zwrotna": "Giving feedback", "Spotkania online": "Online meetings",
    "Profesjonalny e-mail": "A professional email", "Konferencje i wydarzenia": "Conferences and events",
    "Rozmowa kwalifikacyjna": "Job interview", "Networking na konferencji": "Networking at a conference",
    "Pytania po prezentacji projektu": "Questions after a project presentation",
    "Spotkanie z klientem": "Meeting a client", "Rozmowa telefoniczna": "A phone call",
    "Problem z terminem w zespole": "A deadline problem in the team",
    "Egzamin ósmoklasisty — język angielski (ścieżka demonstracyjna)":
        "Polish 8th-grade exam — English (demonstration path)",
    "Słuchanie": "Listening", "Czytanie": "Reading", "Gramatyka i słownictwo": "Grammar and vocabulary",
    "Wypowiedź pisemna (e-mail)": "Writing (email)",
    "Brak zweryfikowanych materiałów i automatycznej oceny — ten obszar nie jest sprawdzany przez aplikację.":
        "No verified materials or automatic scoring — the app does not check this part.",
    "Biblioteka ćwiczeń jest mała i niezweryfikowana przez człowieka; to nie są zadania CKE.":
        "The practice library is small and not reviewed by a human; these are not official CKE tasks.",
    "nie sprawdzono": "not tested", "nie sprawdzane przez aplikację": "not checked by the app",
    "za mało danych": "not enough data", "wstępny obraz": "preliminary picture",
    "potwierdzony ćwiczeniami": "confirmed by exercises", "sugestia modelu": "model suggestion",
    "potwierdzony ćwiczeniem kontrolnym": "confirmed by a check exercise",
    "w ćwiczeniu kontrolnym poprawnie — błąd widziany tylko w rozmowie":
        "correct in the check exercise — error seen only in conversation",
    "niepewna transkrypcja STT": "uncertain speech transcript",
    "sugestia modelu (wysoka pewność)": "model suggestion (high confidence)",
    "sugestia modelu (niska pewność)": "model suggestion (low confidence)",
    "ocena wypowiedzi (model)": "answer assessment (model)", "ocena wypowiedzi": "answer assessment",
    "zakwestionowane przez Ciebie": "disputed by you", "oznaczone jako błąd rozpoznania mowy":
        "marked as a speech recognition error",
    "przywrócone": "restored", "poprawa": "improving", "pogorszenie": "getting worse", "bez zmian": "no change",
    "szacunek wstępny": "preliminary estimate",
    "Szkoła i nauka": "School and learning", "Czas wolny": "Free time", "Wakacje": "Holidays",
    "Znajomi i rodzina": "Friends and family", "bez limitu": "no limit", "czasem": "now and then",
    "Podział punktów i dokładny opis zadań należy potwierdzić w Informatorze CKE; aplikacja ich nie odtwarza.":
        "Confirm the points and exact task types in the official CKE guide; the app does not reproduce them.",
    "Egzamin nie ma części ustnej; mówienie ćwiczymy dodatkowo w Quick Chat na tematach egzaminacyjnych.":
        "The exam has no speaking part; practise speaking in Quick Chat on exam topics.",
})
EXACT["To ćwiczenia przygotowawcze na materiałach aplikacji. Wynik nie jest oficjalnym wynikiem egzaminu ani jego "
      "prognozą punktową; ocena gotowości pokazuje tylko, co i jak pewnie sprawdzono."] = (   # `tr` zdejmuje \n z YAML
    "This is preparation practice on the app's materials. The result is not an official exam result or a points "
    "prediction; readiness only shows what was checked and how reliably.")
