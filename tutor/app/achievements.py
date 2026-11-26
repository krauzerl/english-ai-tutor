"""Osiągnięcia (motywacja) — OSOBNO od oceny kompetencji (F7: 100 standardowych + 50 ukrytych).

Każde osiągnięcie = reguła z katalogu `CATALOG`: (metryka, próg) nad FAKTAMI liczonymi wyłącznie z zapisów w bazie
(sesje, tury, próby, obserwacje, diagnoza, przegląd korekt, zdarzenia aplikacji `app_event`). Trwałe i idempotentne
(`achievement` PK profil+kod): wznowienie sesji, restart ani ponowne wywołanie nie naliczają drugi raz; zdobyte
nie znika. Osiągnięcia NIGDY nie zmieniają mastery ani wyników (tylko czytają). Stare kody (F6/F7) zachowane.
Nie nagradzamy klikania ani przypadkowych słów: liczą się ukończone, ocenione albo merytoryczne działania.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from tutor.app import goal as G
from tutor.app import intent as INTENT
from tutor.app import quickchat as QC
from tutor.pedagogy.mastery import MASTERED

CATEGORIES = {"regularity": "Regularność", "lessons": "Lekcje", "conversation": "Rozmowy", "reviews": "Powtórki",
              "improvement": "Poprawa słabych stron", "challenges": "Wyzwania", "assessment": "Diagnoza",
              "milestones": "Kamienie milowe", "secrets": "Sekrety",
              "competence": "Opanowane umiejętności (potwierdzone przez silnik)",
              # stare kategorie (zdobyte wcześniej odznaki): tylko etykiety
              "talk_time": "Czas rozmów", "exams": "Egzaminy"}
CATEGORIES_EN = {"regularity": "Regularity", "lessons": "Lessons", "conversation": "Conversations",
                 "reviews": "Reviews", "improvement": "Improving weak spots", "challenges": "Challenges",
                 "assessment": "Assessment", "milestones": "Milestones", "secrets": "Secrets",
                 "competence": "Mastered skills (confirmed by the engine)", "talk_time": "Conversation time",
                 "exams": "Exams"}


def _a(code, cat, metric, need, pl, en, dpl, den, hint_pl=None, hint_en=None):
    return {"code": code, "category": cat, "metric": metric, "target": need, "name_pl": pl, "name_en": en,
            "desc_pl": dpl, "desc_en": den, "hidden": hint_pl is not None, "hint_pl": hint_pl, "hint_en": hint_en}


def _tiers(prefix, cat, metric, steps, pl, en, dpl, den):
    """Progi jednej metryki (nie więcej niż kilka na metrykę — reszta katalogu to różne warunki)."""
    return [_a(f"{prefix}_{n}", cat, metric, n, pl.format(n=n), en.format(n=n), dpl.format(n=n), den.format(n=n))
            for n in steps]


STANDARD = [
    # --- regularność (14) ---
    _a("streak_3", "regularity", "streak", 3, "Trzy dni z rzędu", "Three days in a row",
       "Uczysz się 3 dni z rzędu.", "Study 3 days in a row."),
    _a("streak_7", "regularity", "streak", 7, "Tydzień nauki", "A week of learning",
       "Uczysz się 7 dni z rzędu.", "Study 7 days in a row."),
    _a("streak_14", "regularity", "streak", 14, "Dwa tygodnie", "Two weeks",
       "Uczysz się 14 dni z rzędu.", "Study 14 days in a row."),
    _a("streak_30", "regularity", "streak", 30, "Miesiąc nauki", "A month of learning",
       "Uczysz się 30 dni z rzędu.", "Study 30 days in a row."),
    _a("days_10", "regularity", "study_days", 10, "Dziesięć dni nauki", "Ten days of learning",
       "10 różnych dni z aktywnością.", "Be active on 10 different days."),
    *_tiers("days", "regularity", "study_days", (30, 60, 100), "{n} dni nauki", "{n} days of learning",
            "{n} różnych dni z aktywnością.", "Be active on {n} different days."),
    *_tiers("weeks", "regularity", "active_weeks", (4, 12), "{n} aktywnych tygodni", "{n} active weeks",
            "Nauka w {n} różnych tygodniach.", "Study in {n} different weeks."),
    _a("months_3", "regularity", "active_months", 3, "Trzy miesiące", "Three months",
       "Aktywność w 3 różnych miesiącach.", "Be active in 3 different months."),
    _a("weekend_4", "regularity", "weekend_days", 4, "Weekendowy rytm", "Weekend rhythm",
       "Nauka w 4 dni weekendowe.", "Study on 4 weekend days."),
    _a("comeback", "regularity", "comeback", 1, "Powrót", "Comeback",
       "Powrót do nauki po co najmniej 7 dniach przerwy.", "Come back after a break of at least 7 days."),
    _a("two_kinds_5", "regularity", "days_two_kinds", 5, "Różnorodny dzień", "A varied day",
       "5 dni z co najmniej dwoma rodzajami nauki.", "5 days with at least two kinds of activity."),
    # --- lekcje (14) ---
    _a("lesson_1", "lessons", "lessons", 1, "Pierwsza lekcja", "First lesson",
       "Ukończona pierwsza lekcja.", "Complete your first lesson."),
    _a("lesson_5", "lessons", "lessons", 5, "Pięć lekcji", "Five lessons",
       "Ukończone 5 lekcji.", "Complete 5 lessons."),
    _a("lesson_20", "lessons", "lessons", 20, "Dwadzieścia lekcji", "Twenty lessons",
       "Ukończone 20 lekcji.", "Complete 20 lessons."),
    _a("lesson_50", "lessons", "lessons", 50, "Pięćdziesiąt lekcji", "Fifty lessons",
       "Ukończone 50 lekcji.", "Complete 50 lessons."),
    *_tiers("perfect", "lessons", "lessons_perfect", (1, 5, 15), "Bez pomyłki ×{n}", "Flawless ×{n}",
            "{n} lekcji, w których każde zadanie było dobrze za pierwszym razem.",
            "{n} lessons with every task right on the first try."),
    *_tiers("skills", "lessons", "skills_practised", (5, 15, 30), "{n} umiejętności w ruchu", "{n} skills in motion",
            "Ćwiczenia z {n} różnych umiejętności.", "Practise {n} different skills."),
    _a("areas_4", "lessons", "areas_practised", 4, "Cztery strony języka", "Four sides of language",
       "Zadania z 4 różnych obszarów (np. gramatyka, słownictwo, czytanie, słuchanie).",
       "Tasks from 4 different areas (e.g. grammar, vocabulary, reading, listening)."),
    _a("hint_wins_10", "lessons", "hint_successes", 10, "Wskazówka wystarczy", "A hint is enough",
       "10 zadań poprawionych po pierwszej wskazówce.", "Fix 10 tasks after the first hint."),
    _a("lesson_day_3", "lessons", "lessons_day_max", 3, "Trzy misje jednego dnia", "Three missions in a day",
       "3 ukończone lekcje tego samego dnia.", "Complete 3 lessons on the same day."),
    _a("first_try_10", "lessons", "first_try_streak", 10, "Dziesięć celnych", "Ten in a row",
       "10 kolejnych zadań poprawnie za pierwszym razem.", "10 tasks in a row right on the first try."),
    # --- rozmowy (18) ---
    _a("talk_10m", "conversation", "talk_minutes", 10, "Pierwsze 10 minut", "First 10 minutes",
       "10 minut rozmów.", "10 minutes of conversation."),
    _a("talk_60m", "conversation", "talk_minutes", 60, "Godzina rozmów", "An hour of talking",
       "60 minut rozmów.", "60 minutes of conversation."),
    _a("talk_300m", "conversation", "talk_minutes", 300, "Pięć godzin rozmów", "Five hours of talking",
       "300 minut rozmów.", "300 minutes of conversation."),
    _a("talk_1000m", "conversation", "talk_minutes", 1000, "Tysiąc minut", "A thousand minutes",
       "1000 minut rozmów.", "1000 minutes of conversation."),
    *_tiers("chats", "conversation", "chats", (1, 10, 50), "Rozmowy: {n}", "Conversations: {n}",
            "{n} zakończonych rozmów (co najmniej 3 wypowiedzi).",
            "{n} finished conversations (at least 3 answers each)."),
    _a("topics_5", "conversation", "chat_categories", 5, "Odkrywca tematów", "Topic explorer",
       "Rozmowy z 5 różnych kategorii tematów.", "Talk in 5 different topic categories."),
    _a("modes_3", "conversation", "chat_modes", 3, "Trzy style rozmowy", "Three ways to talk",
       "Rozmowa naturalna, prowadzona i roleplay.", "Try natural, guided and role-play conversations."),
    *_tiers("roleplay", "conversation", "roleplays", (1, 10), "Roleplay ×{n}", "Role-play ×{n}",
            "{n} ukończonych scenek (co najmniej 4 wypowiedzi).", "{n} completed role-plays (at least 4 answers)."),
    _a("scenarios_8", "conversation", "roleplay_scenarios", 8, "Osiem sytuacji", "Eight situations",
       "8 różnych scenariuszy roleplay.", "8 different role-play scenarios."),
    _a("long_answers_20", "conversation", "long_answers", 20, "Rozwinięte odpowiedzi", "Developed answers",
       "20 wypowiedzi po co najmniej 25 słów.", "20 answers of at least 25 words."),
    _a("voice_50", "conversation", "voice_turns", 50, "Własnym głosem", "In your own voice",
       "50 wypowiedzi głosem.", "50 spoken answers."),
    _a("voice_300", "conversation", "voice_turns", 300, "Mówca", "Speaker",
       "300 wypowiedzi głosem.", "300 spoken answers."),
    _a("levels_3", "conversation", "chat_levels", 3, "Trzy poziomy", "Three levels",
       "Rozmowy na 3 różnych poziomach trudności.", "Talk at 3 different difficulty levels."),
    _a("custom_3", "conversation", "custom_topics", 3, "Własne tematy", "Your own topics",
       "3 rozmowy na własny temat.", "3 conversations on your own topic."),
    _a("chat_20m", "conversation", "chat_minutes_max", 20, "Długa rozmowa", "A long conversation",
       "Jedna rozmowa trwająca co najmniej 20 minut aktywnie.", "One conversation of at least 20 active minutes."),
    # --- powtórki (12) ---
    _a("review_10", "reviews", "reviews", 10, "Dziesięć powtórek", "Ten reviews",
       "10 zadań powtórkowych.", "10 review tasks."),
    _a("review_50", "reviews", "reviews", 50, "Pięćdziesiąt powtórek", "Fifty reviews",
       "50 zadań powtórkowych.", "50 review tasks."),
    _a("review_200", "reviews", "reviews", 200, "Dwieście powtórek", "Two hundred reviews",
       "200 zadań powtórkowych.", "200 review tasks."),
    _a("review_500", "reviews", "reviews", 500, "Pięćset powtórek", "Five hundred reviews",
       "500 zadań powtórkowych.", "500 review tasks."),
    *_tiers("review_ok", "reviews", "review_correct", (25, 100), "Pamiętam: {n}", "I remember: {n}",
            "{n} poprawnych odpowiedzi w powtórkach.", "{n} correct review answers."),
    *_tiers("retention", "reviews", "retention7", (5, 25, 75), "Pamięć po tygodniu ×{n}",
            "Remembered after a week ×{n}",
            "{n} poprawnych odpowiedzi po co najmniej 7 dniach przerwy.",
            "{n} correct answers after a break of at least 7 days."),
    _a("review_days_10", "reviews", "review_days", 10, "Powtórki w rytmie", "Reviews in rhythm",
       "Powtórki w 10 różnych dniach.", "Reviews on 10 different days."),
    _a("review_streak_10", "reviews", "review_streak", 10, "Czysta seria", "A clean run",
       "10 kolejnych poprawnych odpowiedzi w powtórkach.", "10 correct review answers in a row."),
    _a("review_backlog", "reviews", "review_big_session", 1, "Zaległości odrobione", "Backlog cleared",
       "Jedna sesja powtórek z co najmniej 10 zadaniami.", "One review session with at least 10 tasks."),
    # --- poprawa słabych stron (12) ---
    _a("improved_1", "improvement", "errors_improved", 1, "Pierwsza poprawa", "First improvement",
       "Jeden powtarzający się błąd ustępuje.", "One recurring error starts to fade."),
    _a("improved_3", "improvement", "errors_improved", 3, "Trzy poprawione błędy", "Three errors improved",
       "3 błędy wykazują poprawę.", "3 errors show improvement."),
    _a("improved_10", "improvement", "errors_improved", 10, "Dziesięć poprawionych błędów", "Ten errors improved",
       "10 błędów wykazuje poprawę.", "10 errors show improvement."),
    *_tiers("resolved", "improvement", "errors_resolved", (1, 5), "Rozwiązane: {n}", "Resolved: {n}",
            "{n} błędów oznaczonych przez silnik jako rozwiązane.", "{n} errors marked resolved by the engine."),
    *_tiers("drill", "improvement", "drills", (1, 10), "Celowane ćwiczenia ×{n}", "Targeted practice ×{n}",
            "{n} sesji ćwiczeń słabej strony.", "{n} weak-spot practice sessions."),
    *_tiers("selffix", "improvement", "self_corrections", (1, 10), "Sam poprawiam ×{n}", "Self-correction ×{n}",
            "{n} razy poprawiłeś/aś własne zdanie po wskazówce w rozmowie.",
            "Correct your own sentence after a hint in conversation {n} times."),
    _a("journal_review", "improvement", "journal_reviews", 1, "Krytyczny uczeń", "Critical learner",
       "Przejrzałeś/aś korektę w dzienniku i oceniłeś/aś jej trafność.",
       "Review a correction in the journal and judge whether it was right."),
    _a("weak_area_up", "improvement", "weak_area_up", 1, "Słabe staje się mocniejsze", "Weak becomes stronger",
       "Najsłabszy obszar z pierwszej diagnozy ma później wyższy szacunek.",
       "Your weakest area from the first assessment later has a higher estimate."),
    _a("fewer_errors", "improvement", "fewer_errors", 1, "Mniej sugestii błędów", "Fewer error suggestions",
       "Ostatnie 30 ocenionych wypowiedzi ma mniej sugestii błędów niż pierwsze 30.",
       "Your last 30 assessed answers have fewer error suggestions than your first 30."),
    # --- wyzwania (12) ---
    _a("triple_day", "challenges", "triple_day", 1, "Pełny dzień", "A full day",
       "Lekcja, powtórka i rozmowa tego samego dnia.", "A lesson, a review and a conversation on the same day."),
    _a("exam_1", "challenges", "exam_sessions", 1, "Pierwsza próba egzaminacyjna", "First exam practice",
       "Ukończona sesja ćwiczeń egzaminacyjnych.", "Finish an exam practice session."),
    _a("exam_5", "challenges", "exam_sessions", 5, "Pięć prób egzaminacyjnych", "Five exam practices",
       "5 sesji ćwiczeń egzaminacyjnych.", "5 exam practice sessions."),
    _a("exam_no_hint", "challenges", "exam_correct", 20, "Bez podpowiedzi", "No hints needed",
       "20 poprawnych odpowiedzi w ćwiczeniach egzaminacyjnych.", "20 correct answers in exam practice."),
    _a("first_try_25", "challenges", "first_try_streak", 25, "Dwadzieścia pięć celnych", "Twenty-five in a row",
       "25 kolejnych zadań poprawnie za pierwszym razem.", "25 tasks in a row right on the first try."),
    _a("b2_items_10", "challenges", "hard_correct", 10, "Wyżej poprzeczka", "Raising the bar",
       "10 poprawnych odpowiedzi na zadania B2 lub C1.", "10 correct answers to B2 or C1 tasks."),
    _a("c1_items_10", "challenges", "c1_correct", 10, "Poziom C1 w zasięgu", "C1 in reach",
       "10 poprawnych odpowiedzi na zadania C1.", "10 correct answers to C1 tasks."),
    _a("listening_10", "challenges", "listening_correct", 10, "Uważny słuchacz", "Attentive listener",
       "10 poprawnych odpowiedzi w zadaniach ze słuchu.", "10 correct listening answers."),
    _a("reading_10", "challenges", "reading_correct", 10, "Uważny czytelnik", "Attentive reader",
       "10 poprawnych odpowiedzi w zadaniach z czytania.", "10 correct reading answers."),
    _a("week_variety", "challenges", "week_kinds_max", 4, "Tydzień wszystkiego", "A week of everything",
       "W jednym tygodniu: rozmowa, lekcja, powtórka i diagnoza lub ćwiczenia.",
       "In one week: a conversation, a lesson, a review and an assessment or practice."),
    _a("roleplay_medical_3", "challenges", "medical_roleplays", 3, "Na dyżurze", "On shift",
       "3 różne scenki medyczne.", "3 different medical role-plays."),
    _a("roleplay_business_3", "challenges", "business_roleplays", 3, "Przy stole negocjacji",
       "At the negotiating table", "3 różne scenki biznesowe lub zawodowe.",
       "3 different business or professional role-plays."),
    # --- diagnoza (10) ---
    _a("placement_done", "assessment", "placements", 1, "Poznałem swój punkt wyjścia", "I know where I start",
       "Dopasowanie poziomu wykonane (wynik wstępny, nie certyfikat).",
       "Placement done (preliminary result, not a certificate)."),
    *_tiers("assess_areas", "assessment", "assess_areas", (2, 4), "Sprawdzone obszary: {n}", "Areas checked: {n}",
            "Wynik pełnej diagnozy w {n} obszarach.", "Comprehensive assessment results in {n} areas."),
    _a("assess_full", "assessment", "assess_full", 1, "Pełny obraz", "The full picture",
       "Gramatyka, słownictwo, czytanie i słuchanie w jednej diagnozie.",
       "Grammar, vocabulary, reading and listening in one assessment."),
    _a("assess_open", "assessment", "open_tasks", 1, "Własnymi słowami", "In your own words",
       "Zadanie otwarte (pisanie lub mówienie) w diagnozie.", "An open task (writing or speaking) in an assessment."),
    _a("assess_both_open", "assessment", "open_both", 1, "Piszę i mówię", "I write and speak",
       "Zadania otwarte z pisania i z mówienia.", "Open tasks in both writing and speaking."),
    _a("assess_repeat", "assessment", "assessments", 2, "Druga diagnoza", "Second assessment",
       "Dwie ukończone diagnozy — można porównać wyniki.", "Two completed assessments — results can be compared."),
    _a("assess_repeat_4", "assessment", "assessments", 4, "Regularny pomiar", "Regular check-ups",
       "Cztery ukończone diagnozy.", "Four completed assessments."),
    _a("assess_precise", "assessment", "precise_areas", 2, "Precyzyjny pomiar", "Precise measurement",
       "Dwa obszary z wąskim przedziałem niepewności.", "Two areas with a narrow uncertainty range."),
    _a("assess_up", "assessment", "assess_up", 1, "Wyższy szacunek", "A higher estimate",
       "W powtórnej diagnozie obszar ma wyraźnie wyższy szacunek niż wcześniej.",
       "A repeated assessment gives an area a clearly higher estimate than before."),
    # --- kamienie milowe (8) ---
    _a("first_session", "milestones", "sessions", 1, "Początek", "The beginning", "Pierwsza sesja.",
       "Your first session."),
    *_tiers("sessions", "milestones", "sessions", (25, 100), "Sesje: {n}", "Sessions: {n}",
            "{n} sesji nauki.", "{n} learning sessions."),
    _a("turns_100", "milestones", "user_turns", 100, "Sto wypowiedzi", "A hundred answers",
       "100 Twoich wypowiedzi w rozmowach.", "100 of your answers in conversations."),
    _a("turns_1000", "milestones", "user_turns", 1000, "Tysiąc wypowiedzi", "A thousand answers",
       "1000 Twoich wypowiedzi w rozmowach.", "1000 of your answers in conversations."),
    *_tiers("words", "milestones", "words", (1000, 10000), "{n} słów po angielsku", "{n} words in English",
            "Łącznie {n} słów w Twoich wypowiedziach.", "{n} words in your answers in total."),
    _a("attempts_500", "milestones", "attempts", 500, "Pięćset zadań", "Five hundred tasks",
       "500 rozwiązanych zadań.", "500 tasks answered."),
]

SECRETS = [
    _a("s_night_owl", "secrets", "night_session", 1, "Nocny marek", "Night owl",
       "Sesja z co najmniej 10 wypowiedziami lub 5 zadaniami rozpoczęta między 22:00 a 4:00.",
       "A session with 10+ answers or 5+ tasks started between 22:00 and 04:00.",
       "Księżyc zna jedną z Twoich sesji…", "The moon knows about one of your sessions…"),
    _a("s_early_bird", "secrets", "early_session", 1, "Ranny ptaszek", "Early bird",
       "Pełna sesja rozpoczęta między 5:00 a 7:59.", "A full session started between 05:00 and 07:59.",
       "Zanim zadzwoni budzik…", "Before the alarm rings…"),
    _a("s_bilingual", "secrets", "ui_langs", 2, "Dwa języki interfejsu", "Two interface languages",
       "Używałeś/aś interfejsu po polsku i po angielsku.", "You used the interface in Polish and in English.",
       "Ten sam świat, inne słowa.", "Same world, different words."),
    _a("s_monologue", "secrets", "longest_answer", 60, "Monolog", "Monologue",
       "Jedna wypowiedź licząca co najmniej 60 słów.", "One answer of at least 60 words.",
       "Czasem warto powiedzieć więcej.", "Sometimes it pays to say more."),
    _a("s_marathon", "secrets", "chat_minutes_max", 30, "Maraton", "Marathon",
       "Jedna rozmowa trwająca aktywnie co najmniej 30 minut.", "One conversation of at least 30 active minutes.",
       "Długi dystans.", "The long distance."),
    _a("s_graceful_exit", "secrets", "finish_requests", 1, "Eleganckie pożegnanie", "Graceful exit",
       "Zakończyłeś/aś rozmowę, mówiąc o tym po angielsku.", "You ended a conversation by saying so in English.",
       "Są lepsze sposoby niż zamknięcie okna.", "There are nicer ways than closing the window."),
    _a("s_say_again", "secrets", "repeat_requests", 3, "Proszę jeszcze raz", "Say that again",
       "Trzy razy poprosiłeś/aś po angielsku o powtórzenie.", "You asked for a repetition in English three times.",
       "Słuchanie to też umiejętność.", "Listening is a skill too."),
    _a("s_what_means", "secrets", "explain_requests", 3, "Co to znaczy?", "What does it mean?",
       "Trzy razy zapytałeś/aś po angielsku o znaczenie słowa.", "You asked about a word's meaning in English 3 times.",
       "Ciekawość słów.", "Curious about words."),
    _a("s_topic_hopper", "secrets", "topic_changes_max", 3, "Wędrowiec tematów", "Topic wanderer",
       "Trzy zmiany tematu w jednej rozmowie — i nadal rozmawiasz.",
       "Three topic changes in one conversation — and still talking.",
       "Jedna rozmowa, wiele ścieżek.", "One conversation, many paths."),
    _a("s_comeback_30", "secrets", "comeback30", 1, "Powrót po latach", "Long-awaited return",
       "Powrót do nauki po co najmniej 30 dniach przerwy.", "Come back after a break of at least 30 days.",
       "Drzwi zawsze są otwarte.", "The door is always open."),
    _a("s_clear_voice", "secrets", "clear_voice_turns", 20, "Wyraźny głos", "Clear voice",
       "20 wypowiedzi głosem rozpoznanych bez niepewnych słów.",
       "20 spoken answers recognised with no uncertain words.", "Mikrofon lubi Twój głos.",
       "The microphone likes your voice."),
    _a("s_honest_stt", "secrets", "stt_marks", 1, "Uczciwy zapis", "Honest record",
       "Oznaczyłeś/aś korektę jako błąd rozpoznania mowy — dane są dokładniejsze.",
       "You marked a correction as a speech recognition error — the data is more accurate.",
       "Nie każdy błąd jest Twój.", "Not every error is yours."),
    _a("s_fix_transcript", "secrets", "stt_corrections", 1, "Korektor", "Proofreader",
       "Poprawiłeś/aś rozpoznany tekst przed oceną.", "You corrected the recognised text before assessment.",
       "Najpierw sprawdź, co usłyszałem.", "First check what I heard."),
    _a("s_rerecord", "secrets", "stt_rerecords", 1, "Drugie podejście", "Second take",
       "Nagrałeś/aś wypowiedź jeszcze raz zamiast wysłać niepewną.",
       "You recorded again instead of sending an uncertain answer.", "Druga szansa dla mikrofonu.",
       "A second chance for the microphone."),
    _a("s_devils_advocate", "secrets", "disputes", 1, "Adwokat diabła", "Devil's advocate",
       "Zakwestionowałeś/aś korektę modelu w dzienniku.", "You disputed a model correction in the journal.",
       "Model też bywa w błędzie.", "Models can be wrong too."),
    _a("s_full_circle", "secrets", "full_circle", 1, "Pełny obieg", "Full circle",
       "Diagnoza, potem lekcja, potem powtórka — w ciągu 7 dni.",
       "An assessment, then a lesson, then a review — within 7 days.", "Krąg nauki się domyka.",
       "The learning loop closes."),
    _a("s_sky", "secrets", "ceiling_area", 1, "Ponad skalą", "Off the scale",
       "Diagnoza obszaru zakończona sufitem skali (C1 lub wyżej).",
       "An area assessment that hit the top of the scale (C1 or higher).", "Skala ma swój koniec.",
       "Every scale has an end."),
    _a("s_retention_14", "secrets", "retention14", 10, "Słoniowa pamięć", "Elephant memory",
       "10 poprawnych odpowiedzi po co najmniej 14 dniach przerwy.",
       "10 correct answers after a break of at least 14 days.", "Co dwa tygodnie, to zostaje.",
       "What lasts two weeks, stays."),
    _a("s_weekend_both", "secrets", "full_weekends", 2, "Cały weekend", "Whole weekend",
       "Nauka w sobotę i w niedzielę tego samego weekendu — dwa razy.",
       "Study on both Saturday and Sunday of the same weekend — twice.", "Sobota i niedziela razem.",
       "Saturday and Sunday together."),
    _a("s_medic_all", "secrets", "medical_roleplays", 8, "Cały zespół", "The whole crew",
       "8 różnych scenek medycznych.", "8 different medical role-plays.", "Każde wezwanie jest inne.",
       "Every call is different."),
    _a("s_it_all", "secrets", "it_roleplays", 4, "Pełny stos", "Full stack",
       "4 różne scenki IT.", "4 different IT role-plays.", "Od stand-upu do helpdesku.",
       "From stand-up to helpdesk."),
    _a("s_guided_10", "secrets", "guided_chats", 10, "Prowadzony za rękę", "Guided path",
       "10 rozmów w trybie prowadzonym.", "10 conversations in guided mode.", "Ktoś podsuwa zwroty…",
       "Someone suggests phrases…"),
    _a("s_slow_voice", "secrets", "slow_voice_session", 1, "Spokojne tempo", "Calm pace",
       "Rozmowa głosowa przy wolnym tempie mowy nauczyciela.",
       "A voice conversation with the tutor speaking slowly.", "Wolniej znaczy wyraźniej.",
       "Slower means clearer."),
    _a("s_c1_chat", "secrets", "c1_chats", 1, "Rozmowa jak z kolegą", "Talking to a colleague",
       "Rozmowa na poziomie C1 z co najmniej 6 wypowiedziami.", "A C1-level conversation with at least 6 answers.",
       "Najwyższy poziom rozmowy.", "The highest conversation level."),
    _a("s_a1_to_b1", "secrets", "level_climb", 1, "Wspinaczka", "The climb",
       "Rozmawiałeś/aś na poziomie co najmniej dwa stopnie wyżej niż w pierwszej rozmowie.",
       "You talked at least two levels above your first conversation.", "Krok po kroku w górę.",
       "Step by step, upwards."),
    _a("s_perfect_review", "secrets", "perfect_review_sessions", 3, "Bezbłędne powtórki", "Spotless reviews",
       "3 sesje powtórek bez żadnej pomyłki (co najmniej 4 zadania).",
       "3 review sessions with no mistakes (at least 4 tasks).", "Pamięć bez skazy.", "Memory without a flaw."),
    _a("s_hint_free_lesson", "secrets", "hint_free_lessons", 10, "Samodzielny", "Independent",
       "10 lekcji bez żadnej podpowiedzi.", "10 lessons without any hint.", "Bez koła ratunkowego.",
       "No lifeline needed."),
    _a("s_after_hint_20", "secrets", "hint_successes", 25, "Uczę się na wskazówkach", "Learning from hints",
       "25 zadań poprawionych po wskazówce.", "25 tasks fixed after a hint.", "Wskazówka to nie porażka.",
       "A hint is not a failure."),
    _a("s_triple_week", "secrets", "triple_days", 3, "Trzy pełne dni", "Three full days",
       "Trzy dni z lekcją, powtórką i rozmową.", "Three days with a lesson, a review and a conversation.",
       "Pełny dzień, trzy razy.", "A full day, three times."),
    _a("s_listening_all", "secrets", "listening_levels", 5, "Ucho na każdy poziom", "Ears for every level",
       "Poprawne odpowiedzi ze słuchu na wszystkich poziomach A1–C1.",
       "Correct listening answers at every level A1–C1.", "Od A1 do C1 — uszami.", "From A1 to C1 — by ear."),
    _a("s_reading_all", "secrets", "reading_levels", 5, "Oko na każdy poziom", "Eyes for every level",
       "Poprawne odpowiedzi z czytania na wszystkich poziomach A1–C1.",
       "Correct reading answers at every level A1–C1.", "Od A1 do C1 — oczami.", "From A1 to C1 — by eye."),
    _a("s_grammar_all", "secrets", "grammar_levels", 5, "Gramatyka na każdym piętrze", "Grammar on every floor",
       "Poprawne odpowiedzi z gramatyki na wszystkich poziomach A1–C1.",
       "Correct grammar answers at every level A1–C1.", "Wszystkie piętra budynku.", "Every floor of the building."),
    _a("s_vocab_all", "secrets", "vocabulary_levels", 5, "Słowa z każdej półki", "Words from every shelf",
       "Poprawne odpowiedzi ze słownictwa na wszystkich poziomach A1–C1.",
       "Correct vocabulary answers at every level A1–C1.", "Wszystkie półki biblioteki.",
       "Every shelf in the library."),
    _a("s_100_days", "secrets", "study_days", 150, "Sto pięćdziesiąt dni", "A hundred and fifty days",
       "150 różnych dni z nauką.", "150 different days of study.", "Bardzo długa droga.", "A very long road."),
    _a("s_streak_60", "secrets", "streak", 60, "Niezłomny", "Unbreakable",
       "60 dni nauki z rzędu.", "60 days of study in a row.", "Łańcuch, który się nie zrywa.",
       "A chain that never breaks."),
    _a("s_review_1000", "secrets", "reviews", 1000, "Tysiąc powtórek", "A thousand reviews",
       "1000 zadań powtórkowych.", "1000 review tasks.", "Powtarzanie jest matką…", "Repetition is the mother of…"),
    _a("s_words_50k", "secrets", "words", 50000, "Pięćdziesiąt tysięcy słów", "Fifty thousand words",
       "Łącznie 50 000 słów w Twoich wypowiedziach.", "50,000 words in your answers in total.",
       "Prawdziwa powieść.", "A whole novel."),
    _a("s_all_categories", "secrets", "chat_categories", 6, "Wszystkie światy", "All worlds",
       "Rozmowy we wszystkich kategoriach, łącznie z własnym tematem.",
       "Conversations in every category, including your own topic.", "Każdy świat ma swój język.",
       "Every world has its own language."),
    _a("s_new_year", "secrets", "new_year", 1, "Noworoczne postanowienie", "New Year's resolution",
       "Sesja nauki 1 stycznia.", "A study session on 1 January.", "Pierwszy dzień kalendarza.",
       "The first day of the calendar."),
    _a("s_two_profiles", "secrets", "language_settings", 1, "Na swoich zasadach", "On your own terms",
       "Dostosowałeś/aś tempo mowy lub potwierdzanie rozpoznania do siebie.",
       "You adjusted the speech pace or recognition confirmation to suit you.", "Ustawienia też uczą.",
       "Settings can help too."),
    _a("s_exam_perfect", "secrets", "exam_perfect", 1, "Czysta karta", "Clean sheet",
       "Sesja ćwiczeń egzaminacyjnych bez pomyłki (co najmniej 5 zadań).",
       "An exam practice session with no mistakes (at least 5 tasks).", "Żadnego skreślenia.",
       "Not a single cross."),
    _a("s_drill_fixed", "secrets", "drill_then_improved", 1, "Trafiony cel", "Target hit",
       "Po ćwiczeniach słabej strony ten błąd zaczął ustępować.",
       "After weak-spot practice that error started to fade.", "Celowany trening działa.",
       "Targeted training works."),
    _a("s_selffix_streak", "secrets", "self_corrections", 25, "Własny korektor", "Own editor",
       "25 samodzielnych poprawek zdań w rozmowie.", "25 self-corrections in conversation.",
       "Słyszysz własne błędy.", "You can hear your own errors."),
    _a("s_long_roleplay", "secrets", "long_roleplay", 1, "Wczucie w rolę", "In character",
       "Scenka z co najmniej 15 wypowiedziami.", "A role-play with at least 15 answers.",
       "Zostań w roli dłużej.", "Stay in the role longer."),
    _a("s_quiet_week", "secrets", "comeback_after_review", 1, "Pamięć nie zawodzi", "Memory holds",
       "Po co najmniej 7 dniach przerwy wszystkie powtórki dnia powrotu poprawne (min. 3).",
       "After a break of 7+ days, every review on the day you return is correct (min. 3).",
       "Przerwa nie wymazała wiedzy.", "The break did not erase anything."),
    _a("s_first_c1_item", "secrets", "c1_correct", 1, "Pierwszy szczyt", "First summit",
       "Pierwsza poprawna odpowiedź na zadanie C1.", "Your first correct answer to a C1 task.",
       "Coś na najwyższym poziomie.", "Something at the top level."),
    _a("s_assess_all_six", "secrets", "assess_all_six", 1, "Sześć twarzy języka", "Six faces of language",
       "Diagnoza obejmująca wszystkie sześć kompetencji.", "An assessment covering all six skills.",
       "Sprawdź wszystko naraz.", "Check everything at once."),
    _a("s_ten_scenarios_day", "secrets", "roleplays_day_max", 3, "Dzień teatru", "Theatre day",
       "3 różne scenki jednego dnia.", "3 different role-plays on one day.", "Kurtyna w górę!",
       "Curtain up!"),
    _a("s_mixed_input", "secrets", "mixed_input_chats", 5, "Głos i klawiatura", "Voice and keyboard",
       "5 rozmów z wypowiedziami i głosem, i pisanymi.", "5 conversations with both spoken and typed answers.",
       "Każdy sposób jest dobry.", "Every way is a good way."),
    _a("s_ninety_minutes", "secrets", "day_minutes_max", 90, "Półtorej godziny", "Ninety minutes",
       "90 minut aktywnej nauki jednego dnia.", "90 minutes of active study in one day.",
       "Długi, dobry dzień.", "A long, good day."),
]
CATALOG = STANDARD + SECRETS
BY_CODE = {a["code"]: a for a in CATALOG}
assert len(STANDARD) == 100 and len(SECRETS) == 50 and len(BY_CODE) == 150, (len(STANDARD), len(SECRETS))


# --- fakty z zapisów ---
def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _streak(days: list[date]) -> int:
    """Najdłuższa seria kolejnych dni (rekord się nie cofa, więc odznaka jest trwała)."""
    best = run = 0
    prev = None
    for d in sorted(set(days)):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return best


def _events(repo, pid: int) -> list[dict]:
    return [dict(r) for r in repo.conn.execute(
        "SELECT kind, data_json, created_at FROM app_event WHERE profile_id=? ORDER BY id", (pid,))]


def record_event(repo, pid: int, kind: str, data: dict | None = None) -> None:
    """Zdarzenie aplikacji dla osiągnięć (nigdy dowód kompetencji). Bez treści wypowiedzi."""
    repo.conn.execute("INSERT INTO app_event(profile_id,kind,data_json) VALUES (?,?,?)",
                      (pid, kind, json.dumps(data or {})))


def facts(repo, pid: int, now: datetime, pack=None) -> dict:  # noqa: C901 - jedna, liniowa lista metryk
    if pack is None:
        from tutor.pedagogy import content as C
        pack = C.load(repo.get_profile(pid)["target_lang"])
    sessions = repo.list_sessions(pid)
    plans = {s["id"]: repo.get_session_plan(pid, s["id"]) or {} for s in sessions}
    turns = {s["id"]: repo.list_turns(pid, s["id"]) for s in sessions}
    atts = [dict(r) for r in repo.conn.execute("SELECT * FROM attempt WHERE profile_id=? ORDER BY created_at, id",
                                               (pid,))]
    f: Counter = Counter()
    days: list[date] = []
    kinds_by_day: dict[date, set[str]] = {}
    minutes_by_day: Counter = Counter()
    week_kinds: dict[tuple, set[str]] = {}
    roleplay_ids: set[str] = set()
    rp_by_cat: dict[str, set[str]] = {}
    rp_by_day: dict[date, set[str]] = {}
    chat_cats: set[str] = set()
    chat_modes: set[str] = set()
    chat_levels: list[tuple[str, str]] = []
    lvl = ("A1", "A2", "B1", "B2", "C1")
    for s in sessions:
        ts, plan = turns[s["id"]], plans[s["id"]]
        users = [t for t in ts if t["role"] == "user"]
        d = _dt(s["started_at"])
        n_att = sum(1 for a in atts if a["session_id"] == s["id"])
        work = bool(users) or n_att > 0 or bool(plan.get("done") or plan.get("placement") or plan.get("exam")
                                                 or plan.get("assessment"))
        if not work:                                   # pusta sesja (np. kliknięcie i wyjście) się nie liczy
            continue
        days.append(d.date())
        kinds_by_day.setdefault(d.date(), set()).add(s["kind"])
        week_kinds.setdefault(d.isocalendar()[:2], set()).add(s["kind"])
        full = len(users) >= 10 or n_att >= 5
        if full and (d.hour >= 22 or d.hour < 4):
            f["night_session"] = 1
        if full and 5 <= d.hour < 8:
            f["early_session"] = 1
        if d.month == 1 and d.day == 1:
            f["new_year"] = 1
        secs = QC.active_seconds(repo, pid, s["id"]) if ts else 0
        minutes_by_day[d.date()] += secs // 60
        f["talk_minutes"] += secs // 60 if s["kind"] in ("chat", "voice", "lesson") else 0
        f["user_turns"] += len(users)
        for t in users:
            w = len(t["text"].split())
            f["words"] += w
            f["long_answers"] += int(w >= 25)
            f["longest_answer"] = max(f["longest_answer"], w)
            if t["input_mode"] == "voice":
                f["voice_turns"] += 1
                f["clear_voice_turns"] += int(t["low_prob_json"] == "[]")
            intent = INTENT.classify(t["text"])
            f["finish_requests"] += int(intent == "finish")
            f["repeat_requests"] += int(intent == "repeat")
            f["explain_requests"] += int(intent == "explain")
        if s["kind"] == "chat" and len(users) >= 3:
            f["chats"] += 1
            f["chat_minutes_max"] = max(f["chat_minutes_max"], secs // 60)
            topics = plan.get("topics", [])
            f["topic_changes_max"] = max(f["topic_changes_max"], len(topics) - 1)
            cat = plan.get("category") or "general"
            chat_cats.add(cat)
            mode = plan.get("mode") or "natural"
            chat_modes.add(mode)
            if plan.get("level"):
                chat_levels.append((s["started_at"], plan["level"]))
            f["custom_topics"] += int(any(not t.get("id") for t in topics[:1]))
            f["guided_chats"] += int(mode == "guided")
            f["c1_chats"] += int(plan.get("level") == "C1" and len(users) >= 6)
            modes_in = {t["input_mode"] for t in users}
            f["mixed_input_chats"] += int(modes_in == {"voice", "text"})
            if mode == "roleplay" and len(users) >= 4:
                f["roleplays"] += 1
                rid = (topics[0].get("id") if topics else None) or "custom"
                roleplay_ids.add(rid)
                rp_by_cat.setdefault(cat, set()).add(rid)
                rp_by_day.setdefault(d.date(), set()).add(rid)
                f["long_roleplay"] = max(f["long_roleplay"], int(len(users) >= 15))
            if plan.get("slow_voice") and f["voice_turns"]:
                f["slow_voice_session"] = 1
        f["self_corrections"] += sum(1 for x in plan.get("ladder_history", []) if x == "correct")
        if s["kind"] == "drill" and s["status"] == "ended" and n_att:
            f["drills"] += 1
        if s["kind"] == "exam" and plan.get("exam", {}).get("finished"):
            f["exam_sessions"] += 1
            res = plan["exam"].get("results", [])
            if len(res) >= 5 and all(r.get("verdict") == "correct" for r in res):
                f["exam_perfect"] = 1
        if s["kind"] == "review":
            rv = [a for a in atts if a["session_id"] == s["id"]]
            f["review_big_session"] = max(f["review_big_session"], int(len(rv) >= 10))
            f["perfect_review_sessions"] += int(len(rv) >= 4 and all(a["correct"] for a in rv))
        if s["kind"] == "assessment" and plan.get("assessment", {}).get("done"):
            st = plan["assessment"]
            f["assessments"] += 1
            res = st.get("results", {})
            closed = [a for a in ("grammar", "vocabulary", "reading", "listening") if res.get(a)]
            f["assess_full"] = max(f["assess_full"], int(len(closed) == 4))
            open_ = {a for a, ev in (st.get("open") or {}).items() if ev.get("status") == "evidence"}
            f["open_tasks"] += len(open_)
            f["open_both"] = max(f["open_both"], int(open_ == {"writing", "speaking"}))
            f["assess_all_six"] = max(f["assess_all_six"], int(len(closed) == 4 and len(open_) == 2))
    sd = sorted(set(days))
    f["streak"] = _streak(sd)
    f["study_days"] = len(sd)
    f["active_weeks"] = len({d.isocalendar()[:2] for d in sd})
    f["active_months"] = len({(d.year, d.month) for d in sd})
    f["weekend_days"] = sum(1 for d in sd if d.weekday() >= 5)
    sat = {d for d in sd if d.weekday() == 5}
    f["full_weekends"] = sum(1 for d in sat if d + timedelta(days=1) in sd)
    gaps = [(b - a).days for a, b in zip(sd, sd[1:], strict=False)]
    f["comeback"] = int(any(g >= 7 for g in gaps))
    f["comeback30"] = int(any(g >= 30 for g in gaps))
    f["days_two_kinds"] = sum(1 for k in kinds_by_day.values() if len(k) >= 2)
    f["triple_days"] = sum(1 for k in kinds_by_day.values() if {"lesson", "review", "chat"} <= k)
    f["triple_day"] = int(f["triple_days"] >= 1)
    f["week_kinds_max"] = max((len(k & {"chat", "lesson", "review"}) + int(bool(k & {"assessment", "placement",
                               "drill", "exam"})) for k in week_kinds.values()), default=0)
    f["day_minutes_max"] = max(minutes_by_day.values(), default=0)
    f["sessions"] = len(sessions)
    f["chat_categories"] = len(chat_cats)
    f["chat_modes"] = len(chat_modes)
    f["chat_levels"] = len({lv for _, lv in chat_levels})
    if chat_levels:
        first = lvl.index(sorted(chat_levels)[0][1]) if sorted(chat_levels)[0][1] in lvl else 0
        f["level_climb"] = int(any(lv in lvl and lvl.index(lv) - first >= 2 for _, lv in chat_levels))
    f["roleplay_scenarios"] = len(roleplay_ids)
    f["medical_roleplays"] = len(rp_by_cat.get("medical", set()))
    f["business_roleplays"] = len(rp_by_cat.get("business", set()) | rp_by_cat.get("professional", set()))
    f["it_roleplays"] = len(rp_by_cat.get("technical", set()))
    f["roleplays_day_max"] = max((len(v) for v in rp_by_day.values()), default=0)
    # --- lekcje ---
    done = G.completed(repo, pid)
    f["lessons"] = len(done)
    lesson_days: Counter = Counter()
    for s in sessions:
        plan = plans[s["id"]]
        if s["kind"] != "lesson" or not plan.get("items") or len(plan.get("done", [])) < len(plan["items"]):
            continue
        lesson_days[_dt(s["started_at"]).date()] += 1
        la = [a for a in atts if a["session_id"] == s["id"]]
        if la and all(a["correct"] and a["hint_level"] == 0 for a in la):
            f["lessons_perfect"] += 1
        if la and all(a["hint_level"] == 0 for a in la):
            f["hint_free_lessons"] += 1
    f["lessons_day_max"] = max(lesson_days.values(), default=0)
    f["attempts"] = len(atts)
    f["skills_practised"] = len({a["skill_id"] for a in atts})
    seen: set[str] = set()
    run = 0
    last_skill: dict[str, datetime] = {}
    lv_ok: dict[str, set[str]] = {}
    return_day = None
    for a in atts:
        it = pack.items.get(a["item_id"] or "")
        fb = json.loads(a["feedback_json"]) if a["feedback_json"] else {}
        t = _dt(a["created_at"])
        if it:
            f["areas_practised"] = 0                                    # liczone niżej
            lv_ok.setdefault(it.area, set())
            if a["correct"]:
                lv_ok[it.area].add(it.cefr)
                f["hard_correct"] += int(it.cefr in ("B2", "C1"))
                f["c1_correct"] += int(it.cefr == "C1")
                f["listening_correct"] += int(it.area == "listening")
                f["reading_correct"] += int(it.area == "reading")
        f["hint_successes"] += int(a["correct"] and 1 <= a["hint_level"] <= 3)
        first = a["item_id"] not in seen
        seen.add(a["item_id"])
        if first:
            run = run + 1 if (a["correct"] and a["hint_level"] == 0) else 0
            f["first_try_streak"] = max(f["first_try_streak"], run)
        if fb.get("review"):
            f["reviews"] += 1
            f["review_correct"] += int(a["correct"])
        prev = last_skill.get(a["skill_id"])
        if prev and a["hint_level"] == 0 and a["correct"]:
            f["retention7"] += int((t - prev).days >= 7)
            f["retention14"] += int((t - prev).days >= 14)
        last_skill[a["skill_id"]] = t
        if s_session_kind(sessions, a["session_id"]) == "exam":
            f["exam_correct"] += int(a["correct"])
    f["areas_practised"] = len([k for k in lv_ok])
    for area in ("listening", "reading", "grammar", "vocabulary"):
        f[f"{area}_levels"] = len(lv_ok.get(area, set()) & set(lvl))
    revs = [a for a in atts if (json.loads(a["feedback_json"]) if a["feedback_json"] else {}).get("review")]
    f["review_days"] = len({_dt(a["created_at"]).date() for a in revs})
    run = 0
    for a in revs:
        run = run + 1 if a["correct"] else 0
        f["review_streak"] = max(f["review_streak"], run)
    for i, d in enumerate(sd[1:], 1):                    # powrót po przerwie: powtórki dnia powrotu
        if (d - sd[i - 1]).days >= 7:
            return_day = d
            day_revs = [a for a in revs if _dt(a["created_at"]).date() == return_day]
            if len(day_revs) >= 3 and all(a["correct"] for a in day_revs):
                f["comeback_after_review"] = 1
    # --- błędy, dziennik ---
    errs = [dict(e) for e in repo.list_errors(pid)]
    f["errors_improved"] = sum(1 for e in errs if e["status"] in ("improving", "resolved"))
    f["errors_resolved"] = sum(1 for e in errs if e["status"] == "resolved")
    reviews = list(repo.observation_reviews(pid).values())
    f["disputes"] = sum(1 for r in reviews if r["verdict"] == "disputed")
    f["stt_marks"] = sum(1 for r in reviews if r["verdict"] == "stt_error")
    f["journal_reviews"] = len(reviews)
    drilled = {(plans[s["id"]].get("drill") or {}).get("category") for s in sessions if s["kind"] == "drill"}
    f["drill_then_improved"] = int(any(e["category"] in drilled and e["status"] in ("improving", "resolved")
                                       for e in errs))
    evs = repo.conn.execute(
        "SELECT t.id FROM turn t JOIN turn_meta m ON m.turn_id=t.id WHERE t.profile_id=? AND t.role='user' AND "
        "m.eval_status='evaluated' ORDER BY t.id", (pid,)).fetchall()
    if len(evs) >= 60:
        bad = {r[0] for r in repo.conn.execute(
            "SELECT turn_id FROM observation WHERE profile_id=? AND kind='error' AND status='valid' AND "
            "confidence='h'", (pid,))}
        first30 = sum(1 for (tid,) in evs[:30] if tid in bad)
        last30 = sum(1 for (tid,) in evs[-30:] if tid in bad)
        f["fewer_errors"] = int(last30 < first30)
    # --- diagnoza ---
    comp = [r for r in repo.list_competence(pid)]
    f["placements"] = int(any(r["source"] == "placement_provisional" for r in comp))
    ass = [r for r in comp if r["source"] == "assessment_provisional"]
    f["assess_areas"] = len({r["area"] for r in ass})
    latest = {}
    by_area: dict[str, list[dict]] = {}
    for r in ass:
        latest[r["area"]] = r
        by_area.setdefault(r["area"], []).append(r)
    f["precise_areas"] = sum(1 for r in latest.values() if r["se"] <= 0.35)
    f["assess_up"] = int(any(len(v) >= 2 and v[-1]["theta"] - v[0]["theta"] >= 0.5 for v in by_area.values()))
    f["ceiling_area"] = int(any((json.loads(r["rationale"]) if r["rationale"] else {}).get("ceiling") for r in ass))
    if by_area:
        first_res = {a: v[0]["theta"] for a, v in by_area.items()}
        weakest = min(first_res, key=first_res.get)
        f["weak_area_up"] = int(len(by_area[weakest]) >= 2 and by_area[weakest][-1]["theta"] > first_res[weakest])
    kinds_seq = sorted((_dt(s["started_at"]), s["kind"]) for s in sessions if s["kind"] in ("assessment", "lesson",
                                                                                             "review"))
    for i, (t0, k0) in enumerate(kinds_seq):
        if k0 != "assessment":
            continue
        rest = [(t, k) for t, k in kinds_seq[i + 1:] if (t - t0).days <= 7]
        li = next((j for j, (_, k) in enumerate(rest) if k == "lesson"), None)
        if li is not None and any(k == "review" for _, k in rest[li + 1:]):
            f["full_circle"] = 1
    # --- zdarzenia aplikacji ---
    for e in _events(repo, pid):
        data = json.loads(e["data_json"] or "{}")
        if e["kind"] == "ui_lang":
            f.setdefault("_langs", set()).update({data.get("value"), data.get("from")} - {None})
        elif e["kind"] == "stt_corrected":
            f["stt_corrections"] += 1
        elif e["kind"] == "stt_rerecord":
            f["stt_rerecords"] += 1
        elif e["kind"] == "setting" and data.get("key") in ("speed", "stt_confirm"):
            f["language_settings"] = 1
    f["ui_langs"] = len(f.pop("_langs", set()))
    return dict(f)


def s_session_kind(sessions: list[dict], sid: int | None) -> str | None:
    return next((s["kind"] for s in sessions if s["id"] == sid), None)


def award(repo, pid: int, now: datetime | None = None, pack=None) -> list[dict]:
    """Przyznaje zasłużone osiągnięcia; zwraca TYLKO nowe (idempotentne)."""
    now = now or datetime.now(UTC)
    f = facts(repo, pid, now, pack)
    new = []
    for a in CATALOG:
        if f.get(a["metric"], 0) >= a["target"] and repo.add_achievement(
                pid, a["code"], {"metric": a["metric"], "value": f.get(a["metric"], 0)}):
            new.append(_public(a, True, None, f))
    for s in repo.list_skill_states(pid):
        if s["status"] in MASTERED and repo.add_achievement(pid, f"mastered:{s['skill_id']}",
                                                            {"skill": s["skill_id"], "status": s["status"]}):
            new.append({"code": f"mastered:{s['skill_id']}", "category": "competence", "hidden": False,
                        "name": "Opanowana umiejętność", "name_en": "Mastered skill",
                        "description": s["skill_id"], "description_en": s["skill_id"]})
    return new


def _public(a: dict, earned: bool, earned_at: str | None, f: dict) -> dict:
    """Widok dla GUI. Ukryte niezdobyte: tylko symbol i wskazówka, bez nazwy, opisu i postępu."""
    secret = a["hidden"] and not earned
    return {"code": a["code"], "category": a["category"], "hidden": a["hidden"], "earned": earned,
            "earned_at": earned_at, "target": None if secret else a["target"],
            "progress": None if secret else min(f.get(a["metric"], 0), a["target"]),
            "name": "???" if secret else a["name_pl"], "name_en": "???" if secret else a["name_en"],
            "description": a["hint_pl"] if secret else a["desc_pl"],
            "description_en": a["hint_en"] if secret else a["desc_en"]}


def stats(repo, pid: int, now: datetime) -> dict:
    """Zgodność wsteczna (ekran startowy): kilka metryk z `facts`."""
    f = facts(repo, pid, now)
    return {"streak": f.get("streak", 0), "study_days": f.get("study_days", 0), **f}


def overview(repo, pid: int, now: datetime | None = None, pack=None) -> dict:
    now = now or datetime.now(UTC)
    f = facts(repo, pid, now, pack)
    earned = {a["code"]: a for a in repo.list_achievements(pid)}
    items = [_public(a, a["code"] in earned, earned[a["code"]]["earned_at"] if a["code"] in earned else None, f)
             for a in CATALOG]
    for code, a in earned.items():
        if code.startswith("mastered:"):
            sk = json.loads(a["evidence_json"]).get("skill", "")
            items.append({"code": code, "category": "competence", "hidden": False, "earned": True,
                          "earned_at": a["earned_at"], "progress": 1, "target": 1,
                          "name": "Opanowana umiejętność", "name_en": "Mastered skill", "description": sk,
                          "description_en": sk})
        elif code not in BY_CODE:                         # stary kod spoza katalogu: zostaje widoczny
            items.append({"code": code, "category": "milestones", "hidden": False, "earned": True,
                          "earned_at": a["earned_at"], "progress": 1, "target": 1, "name": code, "name_en": code,
                          "description": "", "description_en": ""})
    std = [i for i in items if not i["hidden"]]
    sec = [i for i in items if i["hidden"]]
    return {"earned": sum(1 for i in items if i["earned"]), "total": len(items), "items": items,
            "standard": {"earned": sum(i["earned"] for i in std), "total": len(std)},
            "secret": {"earned": sum(i["earned"] for i in sec), "total": len(sec)},
            "categories": CATEGORIES, "categories_en": CATEGORIES_EN,
            "note": "Osiągnięcia motywują; nie są oceną kompetencji."}
