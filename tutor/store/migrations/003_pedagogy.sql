-- Silnik dydaktyczny (04_PEDAGOGY_SPEC §7). Tylko ADD COLUMN i nowe tabele: runner działa z foreign_keys=ON
-- w transakcji, więc DROP/RENAME `profile` skasowałby kaskadowo dane ucznia.
--
-- Odstępstwa od §7 (decyzje użytkownika):
--  * correction_style DEFAULT 'summary' (nie 'periodic'): brama jakości oceny Bielika (F8) jeszcze niespełniona;
--    istniejące profile też dostają 'summary' (dotychczasowe 'immediate' było wartością domyślną, nie wyborem).
--  * idempotencja: attempt.dedupe_key (unikalny), unikalny klucz obserwacji, turn_meta.eval_status/applied_at.
ALTER TABLE profile ADD COLUMN correction_style TEXT NOT NULL DEFAULT 'summary'
  CHECK (correction_style IN ('summary','periodic','intensive'));
UPDATE profile SET correction_style = 'summary';
ALTER TABLE profile ADD COLUMN allow_unreviewed_practice INTEGER NOT NULL DEFAULT 1
  CHECK (allow_unreviewed_practice IN (0,1));

ALTER TABLE skill_state ADD COLUMN status TEXT NOT NULL DEFAULT 'new'
  CHECK (status IN ('new','learning','mastered','retained_7d','retained_30d'));
ALTER TABLE skill_state ADD COLUMN verify_due_at TEXT;
ALTER TABLE skill_state ADD COLUMN verified_7d_at TEXT;
ALTER TABLE skill_state ADD COLUMN verified_30d_at TEXT;
ALTER TABLE skill_state ADD COLUMN relapses INTEGER NOT NULL DEFAULT 0;

ALTER TABLE attempt ADD COLUMN source TEXT NOT NULL DEFAULT 'practice'
  CHECK (source IN ('diagnosis','practice','conversation','correction','retention','remediation'));
ALTER TABLE attempt ADD COLUMN hint_level INTEGER NOT NULL DEFAULT 0 CHECK (hint_level BETWEEN 0 AND 4);
ALTER TABLE attempt ADD COLUMN dedupe_key TEXT;   -- ponowna analiza tej samej wypowiedzi nie dubluje próby
CREATE UNIQUE INDEX attempt_dedupe ON attempt(profile_id, dedupe_key) WHERE dedupe_key IS NOT NULL;

ALTER TABLE error_log ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
  CHECK (status IN ('active','recurring','improving','resolved'));
ALTER TABLE error_log ADD COLUMN severity_max INTEGER NOT NULL DEFAULT 1;
ALTER TABLE error_log ADD COLUMN reopened INTEGER NOT NULL DEFAULT 0;
ALTER TABLE error_log ADD COLUMN example_observation_id INTEGER;

CREATE TABLE observation (
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  session_id INTEGER NOT NULL,
  turn_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('error','natural','variant','stt_suspect','disfluency')),
  category TEXT, skill_id TEXT, span TEXT NOT NULL, fix TEXT,
  severity INTEGER CHECK (severity BETWEEN 1 AND 3),
  confidence TEXT CHECK (confidence IN ('h','m','l')),
  status TEXT NOT NULL DEFAULT 'valid' CHECK (status IN ('valid','dropped')),
  drop_reason TEXT, model TEXT, prompt_version TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY (turn_id, session_id, profile_id) REFERENCES turn(id, session_id, profile_id) ON DELETE CASCADE
);
CREATE INDEX observation_session ON observation(profile_id, session_id);
CREATE UNIQUE INDEX observation_dedupe ON observation(profile_id, turn_id, kind, span, IFNULL(category,''), status);

-- Jeden wiersz na przeanalizowaną turę. eval_status rozróżnia: poprawną wypowiedź (evaluated, 0 obserwacji)
-- od nieocenionej (unrated), przerwanej (aborted) i odrzuconej (rejected: niepoprawny wynik modelu).
-- Tylko `evaluated` wchodzi do mianowników ocen; brak oceny nigdy nie jest „poprawną wypowiedzią”.
CREATE TABLE turn_meta (
  turn_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
  profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  input_mode TEXT NOT NULL CHECK (input_mode IN ('text','voice')),
  comm TEXT CHECK (comm IN ('ok','partial','fail','na')),
  comm_quote TEXT,        -- dowód komunikatywności (dosłowny cytat); bez cytatu comm = 'na'
  fluency_json TEXT,      -- tylko metryki zagregowane, bez znaczników czasu pojedynczych słów
  low_prob_words TEXT,    -- JSON listy słów o prob < 0,5 (do walidacji STT)
  eval_status TEXT NOT NULL DEFAULT 'unrated'
    CHECK (eval_status IN ('evaluated','unrated','aborted','rejected')),
  model TEXT, prompt_version TEXT,
  applied_at TEXT,        -- kiedy wynik zastosowano do postępów; niepuste = ponowna analiza jest no-op
  PRIMARY KEY (turn_id),
  FOREIGN KEY (turn_id, session_id, profile_id) REFERENCES turn(id, session_id, profile_id) ON DELETE CASCADE
);
