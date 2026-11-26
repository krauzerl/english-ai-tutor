-- F7 jakość (addytywna): domyślna polityka korekt „zrównoważona”, przegląd korekt przez ucznia, zdarzenia aplikacji.
-- 1) Decyzja właściciela po teście: domyślnie `periodic` („zrównoważona”). Wcześniejsze `summary` pochodziło
--    z domyślnej wartości migracji 003, nie z wyboru ucznia (ustawienie można zmienić w Ustawieniach).
UPDATE profile SET correction_style = 'periodic' WHERE correction_style = 'summary';

-- 2) Uczeń może zakwestionować korektę albo oznaczyć ją jako błąd rozpoznania mowy. Obserwacja zostaje (ślad),
--    wpis przeglądu ją wyłącza z dziennika słabych stron, podsumowań i rejestru błędów. Ostatni wpis wygrywa.
CREATE TABLE observation_review (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    observation_id INTEGER NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('disputed','stt_error','accepted','restored')),
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX observation_review_obs ON observation_review(profile_id, observation_id, id);

-- 3) Zdarzenia aplikacji (odkrywanie funkcji, ustawienia, ekrany) — tylko dla osiągnięć; nigdy dowód kompetencji.
CREATE TABLE app_event (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX app_event_kind ON app_event(profile_id, kind);
