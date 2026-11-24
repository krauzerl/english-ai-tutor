-- Produkt: trwałe osiągnięcia (PK = brak podwójnego naliczania) i ustawienia per profil. Tylko CREATE TABLE.
CREATE TABLE achievement (
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (profile_id, code)
);
CREATE TABLE profile_setting (
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY (profile_id, key)
);
