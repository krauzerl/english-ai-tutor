-- Pilot: learning logs na istniejącym dzienniku zdarzeń (`app_event`), bez nowego, równoległego magazynu.
-- Tylko ADD COLUMN i indeks (bez przebudowy tabel: runner działa z foreign_keys=ON). Stare wiersze: session_id NULL.
-- `app_event` przestaje być „tylko dla osiągnięć”: rodzaje `log.*` i `report.*` to dziennik nauki i zgłoszenia ucznia
-- (achievements czytają wyłącznie swoje rodzaje: ui_lang, setting, stt_corrected, stt_rerecord).
ALTER TABLE app_event ADD COLUMN session_id INTEGER;
CREATE INDEX app_event_session ON app_event(profile_id, session_id, id);
