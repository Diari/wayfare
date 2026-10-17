-- Wayfare Site database (D1, binding "DB"). The worker also creates these
-- tables if they are missing, so a Site works even before migrations run.
CREATE TABLE IF NOT EXISTS actions (
  alert_id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  status TEXT NOT NULL,          -- done | ignored | snoozed
  until TEXT,
  title TEXT,
  by_email TEXT,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todos (
  id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0,
  by_email TEXT,
  at TEXT NOT NULL,
  done_at TEXT
);
CREATE TABLE IF NOT EXISTS packing (
  email TEXT NOT NULL,
  item_id TEXT NOT NULL,
  PRIMARY KEY (email, item_id)
);
