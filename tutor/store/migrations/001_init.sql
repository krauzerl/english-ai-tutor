-- Dane ucznia: każda tabela ma profile_id ON DELETE CASCADE.
-- Własność rekordów wymuszona kluczami złożonymi (id, profile_id): dziecko nie może
-- wskazać rodzica innego profilu. Brak ON UPDATE CASCADE => zmiana właściciela rodzica
-- z dziećmi jest odrzucana.
-- Dane globalne (skill, item) są poza bazą ucznia: ładowane z content/<lang>/ (F3),
-- tu nie ma ich tabel, a kolumny skill_id/item_id to zwykłe teksty bez FK.

CREATE TABLE profile (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(name)) > 0),
    target_lang TEXT NOT NULL DEFAULT 'en',
    ui_lang TEXT NOT NULL DEFAULT 'pl',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    goals_json TEXT NOT NULL DEFAULT '{}',
    daily_minutes INTEGER NOT NULL DEFAULT 30 CHECK (daily_minutes > 0),
    correction_mode TEXT NOT NULL DEFAULT 'immediate' CHECK (correction_mode IN ('immediate','summary')),
    external_api_consent_at TEXT
);

CREATE TABLE skill_state (
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL,
    p_mastery REAL NOT NULL CHECK (p_mastery BETWEEN 0 AND 1),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_seen TEXT,
    mastered_at TEXT,
    PRIMARY KEY (profile_id, skill_id)
);

CREATE TABLE competence (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    area TEXT NOT NULL,
    cefr TEXT NOT NULL,
    theta REAL NOT NULL,
    se REAL NOT NULL,
    n_items INTEGER NOT NULL,
    source TEXT NOT NULL,
    rationale TEXT,
    measured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX competence_profile_area ON competence(profile_id, area, measured_at);

CREATE TABLE diagnosis_run (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at TEXT,
    state_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE session (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    planned_minutes INTEGER,
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at TEXT,
    plan_json TEXT,
    model_json TEXT,
    UNIQUE (id, profile_id)
);
CREATE INDEX session_profile ON session(profile_id, started_at);

CREATE TABLE turn (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (session_id, profile_id) REFERENCES session(id, profile_id) ON DELETE CASCADE,
    UNIQUE (id, session_id, profile_id)
);
CREATE INDEX turn_session ON turn(session_id, id);

CREATE TABLE checkpoint (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    upto_turn_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (session_id, profile_id) REFERENCES session(id, profile_id) ON DELETE CASCADE,
    FOREIGN KEY (upto_turn_id, session_id, profile_id) REFERENCES turn(id, session_id, profile_id) ON DELETE CASCADE
);

-- Historia prób: wiele wierszy na (profil, umiejętność), bez UNIQUE; dzień do mastery
-- ("p>=0.85 w >=2 różnych dniach") z kolumny generowanej.
CREATE TABLE attempt (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    item_id TEXT,
    skill_id TEXT NOT NULL,
    session_id INTEGER,
    correct INTEGER NOT NULL CHECK (correct IN (0,1)),
    score REAL,
    response TEXT,
    feedback_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    day TEXT GENERATED ALWAYS AS (substr(created_at, 1, 10)) VIRTUAL,
    FOREIGN KEY (session_id, profile_id) REFERENCES session(id, profile_id) ON DELETE CASCADE
);
CREATE INDEX attempt_skill_time ON attempt(profile_id, skill_id, created_at);

CREATE TABLE error_log (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    skill_id TEXT,
    example TEXT,
    correction TEXT,
    count INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_seen TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at TEXT
);
CREATE INDEX error_log_category ON error_log(profile_id, category);

CREATE TABLE vocab (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    lang TEXT NOT NULL,
    term TEXT NOT NULL,
    meaning_pl TEXT,
    example TEXT,
    source TEXT,
    UNIQUE (profile_id, lang, term)
);

CREATE TABLE srs_card (
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    card_type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    fsrs_json TEXT NOT NULL,
    due_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, card_type, ref_id)
);
CREATE INDEX srs_card_due ON srs_card(profile_id, due_at);

-- Klucz własny `id`: tygodnie/miesiące nie mają session_id (stary PK session_id to wykluczał).
CREATE TABLE session_summary (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
    level TEXT NOT NULL CHECK (level IN ('session','week','month')),
    session_id INTEGER,
    period_start TEXT,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((level = 'session' AND session_id IS NOT NULL AND period_start IS NULL)
        OR (level <> 'session' AND session_id IS NULL AND period_start IS NOT NULL)),
    FOREIGN KEY (session_id, profile_id) REFERENCES session(id, profile_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX session_summary_session ON session_summary(profile_id, session_id)
    WHERE level = 'session';
CREATE UNIQUE INDEX session_summary_period ON session_summary(profile_id, level, period_start)
    WHERE level <> 'session';

CREATE TABLE next_plan (
    profile_id INTEGER PRIMARY KEY REFERENCES profile(id) ON DELETE CASCADE,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE llm_usage (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profile(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    role TEXT NOT NULL,
    in_tokens INTEGER NOT NULL DEFAULT 0,
    out_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    cost_usd REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
