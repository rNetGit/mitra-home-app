"""Apply migration 030 to data/family.db (idempotent): saved items (links, notes, places, deals, videos, repos, articles).

One table, `saved_items`, for things the family wants to find again: a git repo, a news article, a YouTube video, a
restaurant, a deal that ends Friday, a plain note. Tags group them; search is plain word matching over title, note,
tags, address, domain and URL (data/saved.py find). Nothing is fetched from the internet: the title is typed by a
person. Only http(s) URLs are stored, tracking parameters stripped, URLs that look like they carry a login token refused.
audience: 'family' (everyone signed in, kids included), 'adults', 'private' (only the person who saved it, on the
dashboard). Nothing is deleted: archive sets status='archived'. Deals with expires_on join data/expiries.py (type deal).
Manage with data/saved.py or the dashboard Family > Saved tab.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS saved_items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'link' CHECK (kind IN ('link','note','place','deal','video','repo','article','social')),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  url TEXT CHECK (url IS NULL OR (length(url) <= 2000 AND (url LIKE 'http://%' OR url LIKE 'https://%'))),
  domain TEXT,
  body TEXT CHECK (body IS NULL OR length(body) <= 5000),
  place_address TEXT CHECK (place_address IS NULL OR length(place_address) <= 200),
  expires_on TEXT CHECK (expires_on IS NULL OR expires_on GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
  tags TEXT,
  audience TEXT NOT NULL DEFAULT 'family' CHECK (audience IN ('family','adults','private')),
  owner TEXT,
  pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0,1)),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  added_at TEXT NOT NULL,
  last_opened TEXT,
  CHECK (audience <> 'private' OR owner IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_saved_items_status ON saved_items(status, kind);
CREATE INDEX IF NOT EXISTS idx_saved_items_expires ON saved_items(expires_on) WHERE expires_on IS NOT NULL;
""")
c.commit()
print("migration 030 ok;", c.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0], "saved items")
