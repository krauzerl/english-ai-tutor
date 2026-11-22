-- F4.6/C2 (07 §3.2): wiedza o słowie. Tylko ADD COLUMN (runner działa z foreign_keys=ON; backup robi `open_db`).
-- Semantyka liczników: recall_ok = liczba RÓŻNYCH dni z poprawnym przywołaniem, recall_fail = porażki z rzędu,
-- used_count = wszystkie poprawne użycia w rozmowie, use_sessions = różne sesje z poprawnym użyciem.
ALTER TABLE vocab ADD COLUMN lemma TEXT;
ALTER TABLE vocab ADD COLUMN knowledge TEXT NOT NULL DEFAULT 'unknown'
  CHECK (knowledge IN ('unknown','passive','active'));
ALTER TABLE vocab ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vocab ADD COLUMN recall_ok INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vocab ADD COLUMN recall_fail INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vocab ADD COLUMN used_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vocab ADD COLUMN last_used_at TEXT;
ALTER TABLE vocab ADD COLUMN last_recall_day TEXT;
ALTER TABLE vocab ADD COLUMN last_use_session INTEGER;
ALTER TABLE vocab ADD COLUMN use_sessions INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vocab ADD COLUMN card_day TEXT;
