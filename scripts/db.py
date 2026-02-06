"""
Database operations for the Flowers bot.
Provides CRUD operations, transaction support, and row locking.
"""

import sqlite3
import json
import time
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'flowers.db')


class Database:
    """Database interface for Flowers bot."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        return conn

    @contextmanager
    def transaction(self):
        """Context manager for database transactions."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== Events ====================

    def create_event(
        self,
        name: str,
        event_date: str,
        time_window: str,
        location_drop_time: str,
        rules: List[str],
        host_phone: str
    ) -> int:
        """Create a new event."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (name, event_date, time_window, location_drop_time,
                                    rules, host_phone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, event_date, time_window, location_drop_time,
                 json.dumps(rules), host_phone, int(time.time()), int(time.time()))
            )
            return cursor.lastrowid

    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        """Get event by ID."""
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if row:
                event = dict(row)
                event['rules'] = json.loads(event['rules']) if event['rules'] else []
                return event
            return None
        finally:
            conn.close()

    def get_active_event(self) -> Optional[Dict[str, Any]]:
        """Get the active event (one event at a time model)."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM events WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                event = dict(row)
                event['rules'] = json.loads(event['rules']) if event['rules'] else []
                return event
            return None
        finally:
            conn.close()

    def update_event(self, event_id: int, **kwargs) -> None:
        """Update event fields."""
        if not kwargs:
            return

        # Special handling for rules (convert to JSON)
        if 'rules' in kwargs:
            kwargs['rules'] = json.dumps(kwargs['rules'])

        kwargs['updated_at'] = int(time.time())

        set_clause = ', '.join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [event_id]

        with self.transaction() as conn:
            conn.execute(f"UPDATE events SET {set_clause} WHERE id = ?", values)

    # ==================== Guests ====================

    def create_guest(
        self,
        event_id: int,
        phone: str,
        invited_by_phone: Optional[str] = None
    ) -> int:
        """Create a new guest record."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO guests (event_id, phone, invited_by_phone, invited_at)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, phone, invited_by_phone, int(time.time()))
            )
            return cursor.lastrowid

    def get_guest(self, guest_id: int, for_update: bool = False) -> Optional[Dict[str, Any]]:
        """Get guest by ID. Use for_update=True to lock the row."""
        conn = self.get_connection()
        try:
            query = "SELECT * FROM guests WHERE id = ?"
            if for_update:
                # Note: SQLite doesn't support SELECT FOR UPDATE directly,
                # but we can use BEGIN IMMEDIATE to lock
                conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(query, (guest_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if not for_update:
                conn.close()
            # If for_update, caller must manage connection

    def get_guest_by_phone(self, phone: str, event_id: int) -> Optional[Dict[str, Any]]:
        """Get guest by phone number and event ID."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM guests WHERE event_id = ? AND phone = ?",
                (event_id, phone)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_guests(
        self,
        event_id: int,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all guests for an event, optionally filtered by status."""
        conn = self.get_connection()
        try:
            if status:
                cursor = conn.execute(
                    "SELECT * FROM guests WHERE event_id = ? AND status = ? ORDER BY invited_at",
                    (event_id, status)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM guests WHERE event_id = ? ORDER BY invited_at",
                    (event_id,)
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def update_guest(self, guest_id: int, **kwargs) -> None:
        """Update guest fields."""
        if not kwargs:
            return

        # Add responded_at timestamp if status is being updated
        if 'status' in kwargs and kwargs['status'] in ('confirmed', 'declined'):
            kwargs['responded_at'] = int(time.time())

        set_clause = ', '.join(f"{key} = ?" for key in kwargs.keys())
        values = list(kwargs.values()) + [guest_id]

        with self.transaction() as conn:
            conn.execute(f"UPDATE guests SET {set_clause} WHERE id = ?", values)

    def search_guests(self, event_id: int, query: str) -> List[Dict[str, Any]]:
        """Search guests by name or phone."""
        conn = self.get_connection()
        try:
            search_pattern = f"%{query}%"
            cursor = conn.execute(
                """
                SELECT * FROM guests
                WHERE event_id = ? AND (name LIKE ? OR phone LIKE ?)
                ORDER BY name, phone
                """,
                (event_id, search_pattern, search_pattern)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==================== Quota Enforcement ====================

    def can_invite_plus_one(self, guest_id: int) -> Tuple[bool, str]:
        """
        Check if guest can invite a +1.

        Returns:
            (can_invite: bool, reason: str)
        """
        guest = self.get_guest(guest_id)
        if not guest:
            return False, "Guest not found"

        if guest['status'] != 'confirmed':
            return False, "Only confirmed guests can invite"

        if guest['quota_used'] >= 1:
            return False, "You've already invited someone"

        return True, "OK"

    def use_quota(self, guest_id: int, invited_phone: str) -> int:
        """
        Mark quota as used and create invite link.
        Atomic transaction to prevent race conditions.

        Args:
            guest_id: ID of guest inviting
            invited_phone: Phone number being invited

        Returns:
            ID of newly created guest

        Raises:
            ValueError: If quota already used or guest not found/confirmed
        """
        with self.transaction() as conn:
            # Lock the guest row
            cursor = conn.execute(
                "SELECT * FROM guests WHERE id = ? LIMIT 1",
                (guest_id,)
            )
            guest = cursor.fetchone()
            if not guest:
                raise ValueError("Guest not found")

            guest = dict(guest)

            if guest['status'] != 'confirmed':
                raise ValueError("Only confirmed guests can invite")

            if guest['quota_used'] >= 1:
                raise ValueError("Quota already used")

            # Create new guest
            new_cursor = conn.execute(
                """
                INSERT INTO guests (event_id, phone, invited_by_phone, invited_at)
                VALUES (?, ?, ?, ?)
                """,
                (guest['event_id'], invited_phone, guest['phone'], int(time.time()))
            )
            new_guest_id = new_cursor.lastrowid

            # Update quota
            conn.execute(
                "UPDATE guests SET quota_used = 1 WHERE id = ?",
                (guest_id,)
            )

            return new_guest_id

    # ==================== Conversation State ====================

    def upsert_conversation_state(
        self,
        event_id: int,
        phone: str,
        state: str,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Create or update conversation state."""
        context_json = json.dumps(context) if context else None

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO conversation_state (event_id, phone, state, context, last_message_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id, phone) DO UPDATE SET
                    state = excluded.state,
                    context = excluded.context,
                    last_message_at = excluded.last_message_at
                """,
                (event_id, phone, state, context_json, int(time.time()))
            )

    def get_conversation_state(self, event_id: int, phone: str) -> Optional[Dict[str, Any]]:
        """Get conversation state for a guest."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM conversation_state WHERE event_id = ? AND phone = ?",
                (event_id, phone)
            )
            row = cursor.fetchone()
            if row:
                state = dict(row)
                state['context'] = json.loads(state['context']) if state['context'] else {}
                return state
            return None
        finally:
            conn.close()

    # ==================== Message Log ====================

    def log_message(
        self,
        from_phone: str,
        to_phone: str,
        message_text: str,
        direction: str,
        event_id: Optional[int] = None
    ) -> int:
        """Log a message."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO message_log (event_id, from_phone, to_phone, message_text, direction, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, from_phone, to_phone, message_text, direction, int(time.time()))
            )
            return cursor.lastrowid

    def get_recent_messages(
        self,
        phone: str,
        event_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent messages for a phone number."""
        conn = self.get_connection()
        try:
            if event_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM message_log
                    WHERE event_id = ? AND (from_phone = ? OR to_phone = ?)
                    ORDER BY timestamp DESC LIMIT ?
                    """,
                    (event_id, phone, phone, limit)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM message_log
                    WHERE from_phone = ? OR to_phone = ?
                    ORDER BY timestamp DESC LIMIT ?
                    """,
                    (phone, phone, limit)
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==================== Instagram Social Graph ====================

    def upsert_ig_follow_status(self, event_id: int, guest_id: int, handle: str, status: str, **kwargs) -> None:
        """Create or update Instagram follow status for a guest."""
        now = int(time.time())
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO ig_follow_status (event_id, guest_id, handle, status, followed_at, scraped_at, following_count, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, guest_id) DO UPDATE SET
                    status = excluded.status,
                    followed_at = COALESCE(excluded.followed_at, ig_follow_status.followed_at),
                    scraped_at = COALESCE(excluded.scraped_at, ig_follow_status.scraped_at),
                    following_count = COALESCE(excluded.following_count, ig_follow_status.following_count),
                    error_message = excluded.error_message
                """,
                (event_id, guest_id, handle, status,
                 kwargs.get('followed_at'), kwargs.get('scraped_at'),
                 kwargs.get('following_count', 0), kwargs.get('error_message'))
            )

    def get_ig_follow_status(self, event_id: int, guest_id: int) -> Optional[Dict[str, Any]]:
        """Get Instagram follow status for a guest."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM ig_follow_status WHERE event_id = ? AND guest_id = ?",
                (event_id, guest_id)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def store_ig_following(self, event_id: int, guest_id: int, guest_handle: str, follows_handles: List[str]) -> int:
        """Batch insert following list for a guest. Returns count inserted."""
        now = int(time.time())
        count = 0
        with self.transaction() as conn:
            for handle in follows_handles:
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO ig_following (event_id, guest_id, guest_handle, follows_handle, scraped_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (event_id, guest_id, guest_handle, handle.lower(), now)
                    )
                    count += 1
                except Exception:
                    pass
        return count

    def find_followers_of(self, event_id: int, target_handle: str) -> List[Dict[str, Any]]:
        """Find confirmed guests whose following list includes target_handle."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT g.id as guest_id, g.name, g.phone, g.instagram, ig.guest_handle
                FROM ig_following ig
                JOIN guests g ON ig.guest_id = g.id AND ig.event_id = g.event_id
                WHERE ig.event_id = ? AND ig.follows_handle = ? AND g.status = 'confirmed'
                """,
                (event_id, target_handle.lower())
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def has_notification_been_sent(self, event_id: int, notified_guest_id: int, about_guest_id: int) -> bool:
        """Check if a mutual connection notification has already been sent."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM ig_notifications_sent WHERE event_id = ? AND notified_guest_id = ? AND about_guest_id = ?",
                (event_id, notified_guest_id, about_guest_id)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def record_notification_sent(self, event_id: int, notified_guest_id: int, about_guest_id: int) -> None:
        """Record that a mutual connection notification was sent."""
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO ig_notifications_sent (event_id, notified_guest_id, about_guest_id, sent_at)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, notified_guest_id, about_guest_id, int(time.time()))
            )

    def get_social_graph(self, event_id: int) -> List[Dict[str, Any]]:
        """Get all intra-event Instagram connections for host display."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT ig.guest_handle, ig.follows_handle, g.name as follower_name,
                       g2.name as followed_name, g2.id as followed_guest_id
                FROM ig_following ig
                JOIN guests g ON ig.guest_id = g.id AND ig.event_id = g.event_id
                JOIN guests g2 ON ig.event_id = g2.event_id AND LOWER(g2.instagram) = '@' || ig.follows_handle
                WHERE ig.event_id = ?
                ORDER BY ig.guest_handle, ig.follows_handle
                """,
                (event_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_ig_stats(self, event_id: int) -> Dict[str, int]:
        """Get Instagram-related stats for an event."""
        conn = self.get_connection()
        try:
            # Guests with IG handles
            cursor = conn.execute(
                "SELECT COUNT(*) as c FROM guests WHERE event_id = ? AND instagram IS NOT NULL",
                (event_id,)
            )
            with_ig = cursor.fetchone()['c']

            # Scraped count
            cursor = conn.execute(
                "SELECT COUNT(*) as c FROM ig_follow_status WHERE event_id = ? AND scraped_at IS NOT NULL",
                (event_id,)
            )
            scraped = cursor.fetchone()['c']

            # Pending count
            cursor = conn.execute(
                "SELECT COUNT(*) as c FROM ig_follow_status WHERE event_id = ? AND (scraped_at IS NULL AND status != 'not_found' AND status != 'error')",
                (event_id,)
            )
            pending = cursor.fetchone()['c']

            # Connections count
            cursor = conn.execute(
                """
                SELECT COUNT(*) as c
                FROM ig_following ig
                JOIN guests g2 ON ig.event_id = g2.event_id AND LOWER(g2.instagram) = '@' || ig.follows_handle
                WHERE ig.event_id = ?
                """,
                (event_id,)
            )
            connections = cursor.fetchone()['c']

            return {
                'with_ig': with_ig,
                'scraped': scraped,
                'pending': pending,
                'connections': connections,
            }
        finally:
            conn.close()

    def get_pending_rescans(self, min_age_seconds: int = 1800) -> List[Dict[str, Any]]:
        """Find ig_follow_status rows needing rescan (requested, not yet scraped, old enough)."""
        cutoff = int(time.time()) - min_age_seconds
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT ifs.event_id, ifs.guest_id, ifs.handle
                FROM ig_follow_status ifs
                WHERE ifs.status = 'requested'
                  AND ifs.scraped_at IS NULL
                  AND ifs.followed_at < ?
                """,
                (cutoff,)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ==================== Stats ====================

    def get_event_stats(self, event_id: int) -> Dict[str, int]:
        """Get statistics for an event."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT
                    status,
                    COUNT(*) as count
                FROM guests
                WHERE event_id = ?
                GROUP BY status
                """,
                (event_id,)
            )
            stats = {row['status']: row['count'] for row in cursor.fetchall()}

            # Add derived stats
            stats['total'] = sum(stats.values())
            stats['confirmed'] = stats.get('confirmed', 0)
            stats['pending'] = stats.get('pending', 0)
            stats['declined'] = stats.get('declined', 0)

            # Count +1s used
            cursor = conn.execute(
                """
                SELECT COUNT(*) as count FROM guests
                WHERE event_id = ? AND quota_used = 1
                """,
                (event_id,)
            )
            stats['plus_ones_used'] = cursor.fetchone()['count']

            return stats
        finally:
            conn.close()


# Global database instance
db = Database()
