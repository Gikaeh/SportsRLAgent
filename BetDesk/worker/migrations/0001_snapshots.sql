-- One row per mirrored DeepSports API response (key = path + sorted query string).
CREATE TABLE snapshots (
  key TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  generated_at TEXT NOT NULL -- ISO time the Mac took the snapshot in which this body last changed
);
CREATE INDEX snapshots_generated_at ON snapshots (generated_at);

-- Newest push (single row, id = 1): drives /api/health and the app's stale banner.
CREATE TABLE meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  generated_at TEXT NOT NULL,
  warehouse TEXT NOT NULL
);
