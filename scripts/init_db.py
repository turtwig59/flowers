#!/usr/bin/env python3
"""
Initialize the Flowers database with schema.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'flowers.db')

SCHEMA = """
-- Events: Store party details
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    time_window TEXT,
    location_drop_time TEXT,
    rules TEXT,
    host_phone TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- Guests: Track all invitees and their state
CREATE TABLE IF NOT EXISTS guests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    phone TEXT NOT NULL,
    name TEXT,
    instagram TEXT,
    status TEXT DEFAULT 'pending',
    invited_by_phone TEXT,
    quota_used INTEGER DEFAULT 0,
    invited_at INTEGER NOT NULL,
    responded_at INTEGER,
    FOREIGN KEY (event_id) REFERENCES events(id),
    UNIQUE(event_id, phone)
);

-- Conversation state: Track where each guest is in the flow
CREATE TABLE IF NOT EXISTS conversation_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    phone TEXT NOT NULL,
    state TEXT NOT NULL,
    context TEXT,
    last_message_at INTEGER NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id),
    UNIQUE(event_id, phone)
);

-- Message log: Audit trail for all messages
CREATE TABLE IF NOT EXISTS message_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    from_phone TEXT NOT NULL,
    to_phone TEXT NOT NULL,
    message_text TEXT NOT NULL,
    direction TEXT NOT NULL,
    timestamp INTEGER NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_guests_event_phone ON guests(event_id, phone);
CREATE INDEX IF NOT EXISTS idx_guests_invited_by ON guests(invited_by_phone);
CREATE INDEX IF NOT EXISTS idx_conversation_state_lookup ON conversation_state(event_id, phone);
CREATE INDEX IF NOT EXISTS idx_message_log_timestamp ON message_log(timestamp DESC);

-- Trigger: Enforce quota (exactly 1 invite per guest)
CREATE TRIGGER IF NOT EXISTS enforce_quota
BEFORE UPDATE ON guests
FOR EACH ROW
WHEN NEW.quota_used > 1
BEGIN
    SELECT RAISE(ABORT, 'Quota exceeded: each guest can only invite one person');
END;

-- Instagram: Who each guest follows (scraped from Instagram)
CREATE TABLE IF NOT EXISTS ig_following (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    guest_id INTEGER NOT NULL,
    guest_handle TEXT NOT NULL,
    follows_handle TEXT NOT NULL,
    scraped_at INTEGER NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (guest_id) REFERENCES guests(id),
    UNIQUE(event_id, guest_id, follows_handle)
);
CREATE INDEX IF NOT EXISTS idx_ig_following_lookup ON ig_following(event_id, follows_handle);

-- Instagram: Bot's follow status per guest
CREATE TABLE IF NOT EXISTS ig_follow_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    guest_id INTEGER NOT NULL,
    handle TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    followed_at INTEGER,
    scraped_at INTEGER,
    following_count INTEGER DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (guest_id) REFERENCES guests(id),
    UNIQUE(event_id, guest_id)
);

-- Instagram: Prevent duplicate mutual connection notifications
CREATE TABLE IF NOT EXISTS ig_notifications_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    notified_guest_id INTEGER NOT NULL,
    about_guest_id INTEGER NOT NULL,
    sent_at INTEGER NOT NULL,
    UNIQUE(event_id, notified_guest_id, about_guest_id)
);
"""

def init_database():
    """Initialize the database with schema."""
    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    # Connect and execute schema
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print(f"Database initialized successfully at {DB_PATH}")
    except Exception as e:
        print(f"Error initializing database: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    init_database()
