-- F5.3: trwały status sesji (wznowienie po restarcie) i tryb wejścia tury (odtwarzanie oczekujących ocen).
-- Tylko ADD COLUMN. `status` zastępuje wnioskowanie z `ended_at` (które zostaje spójne: ended ⇔ ended_at).
ALTER TABLE session ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','ended'));
UPDATE session SET status = 'ended' WHERE ended_at IS NOT NULL;
-- Tryb i słowa o niskim prawdopodobieństwie STT zapisujemy przy turze: bez nich odtworzona tura głosowa
-- byłaby oceniana jak tekstowa (zbyt łagodnie dla podejrzeń STT).
ALTER TABLE turn ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'text' CHECK (input_mode IN ('text','voice'));
ALTER TABLE turn ADD COLUMN low_prob_json TEXT;
