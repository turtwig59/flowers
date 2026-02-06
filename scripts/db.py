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
