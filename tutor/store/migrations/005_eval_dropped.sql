-- F5.2: trwały ślad porzuconej oceny (kolejka oceny, 3 nieudane próby). Tura i tekst zostają; status oceny
-- pozostaje `unrated` (brak oceny nigdy nie jest „poprawną wypowiedzią”). Tylko ADD COLUMN.
ALTER TABLE turn_meta ADD COLUMN dropped_at TEXT;
