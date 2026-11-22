-- Wspólny limit API nie może spadać po usunięciu profilu: wiersze użycia (bez treści) zostają,
-- profile_id -> NULL. Przebudowa tabeli (SQLite nie zmienia FK w miejscu).
CREATE TABLE llm_usage_new (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER REFERENCES profile(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    role TEXT NOT NULL,
    in_tokens INTEGER NOT NULL DEFAULT 0,
    out_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    cost_usd REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO llm_usage_new SELECT * FROM llm_usage;
DROP TABLE llm_usage;
ALTER TABLE llm_usage_new RENAME TO llm_usage;
CREATE INDEX llm_usage_created ON llm_usage(created_at);
