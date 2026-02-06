"""
Unit tests for database operations.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest
import tempfile
import shutil
from db import Database


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test.db')

    # Initialize schema
    from init_db import SCHEMA
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.close()

    db = Database(db_path)
    yield db

    # Cleanup
    shutil.rmtree(temp_dir)


class TestEvents:
    """Tests for event operations."""

    def test_create_event(self, test_db):
        """Test creating an event."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=["No photos", "Be respectful"],
            host_phone="+15551234567"
        )
        assert event_id > 0

        # Verify event was created
        event = test_db.get_event(event_id)
        assert event is not None
        assert event['name'] == "Test Party"
        assert event['host_phone'] == "+15551234567"
        assert event['rules'] == ["No photos", "Be respectful"]
        assert event['status'] == 'active'

    def test_get_active_event(self, test_db):
        """Test getting the active event."""
        event_id = test_db.create_event(
            name="Active Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        active = test_db.get_active_event()
        assert active is not None
        assert active['id'] == event_id
        assert active['name'] == "Active Party"

    def test_update_event(self, test_db):
        """Test updating an event."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        test_db.update_event(event_id, status='completed')

        event = test_db.get_event(event_id)
        assert event['status'] == 'completed'


class TestGuests:
    """Tests for guest operations."""

    def test_create_guest(self, test_db):
        """Test creating a guest."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        guest_id = test_db.create_guest(event_id, "+15559999999")
        assert guest_id > 0

        guest = test_db.get_guest(guest_id)
        assert guest is not None
        assert guest['phone'] == "+15559999999"
        assert guest['status'] == 'pending'
        assert guest['quota_used'] == 0

    def test_get_guest_by_phone(self, test_db):
        """Test getting guest by phone number."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        test_db.create_guest(event_id, "+15559999999")

        guest = test_db.get_guest_by_phone("+15559999999", event_id)
        assert guest is not None
        assert guest['phone'] == "+15559999999"

    def test_update_guest(self, test_db):
        """Test updating a guest."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        guest_id = test_db.create_guest(event_id, "+15559999999")
        test_db.update_guest(guest_id, status='confirmed', name='Alice')

        guest = test_db.get_guest(guest_id)
        assert guest['status'] == 'confirmed'
        assert guest['name'] == 'Alice'
        assert guest['responded_at'] is not None

    def test_get_guests_filtered(self, test_db):
        """Test getting guests filtered by status."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        guest1_id = test_db.create_guest(event_id, "+15551111111")
        guest2_id = test_db.create_guest(event_id, "+15552222222")

        test_db.update_guest(guest1_id, status='confirmed')
        test_db.update_guest(guest2_id, status='declined')

        confirmed = test_db.get_guests(event_id, status='confirmed')
        assert len(confirmed) == 1
        assert confirmed[0]['phone'] == "+15551111111"

        declined = test_db.get_guests(event_id, status='declined')
        assert len(declined) == 1
        assert declined[0]['phone'] == "+15552222222"

    def test_search_guests(self, test_db):
        """Test searching guests."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        guest_id = test_db.create_guest(event_id, "+15559999999")
        test_db.update_guest(guest_id, name='Alice')

        # Search by name
        results = test_db.search_guests(event_id, "Ali")
        assert len(results) == 1
        assert results[0]['name'] == 'Alice'

        # Search by phone
        results = test_db.search_guests(event_id, "9999")
        assert len(results) == 1
        assert results[0]['phone'] == "+15559999999"


class TestQuota:
    """Tests for quota enforcement."""

    def test_can_invite_plus_one(self, test_db):
        """Test checking if guest can invite +1."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        guest_id = test_db.create_guest(event_id, "+15559999999")

        # Pending guest cannot invite
        can_invite, reason = test_db.can_invite_plus_one(guest_id)
        assert can_invite is False
        assert "confirmed" in reason.lower()

        # Confirmed guest can invite
        test_db.update_guest(guest_id, status='confirmed')
        can_invite, reason = test_db.can_invite_plus_one(guest_id)
        assert can_invite is True

    def test_use_quota(self, test_db):
        """Test using quota to invite +1."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        guest_id = test_db.create_guest(event_id, "+15559999999")
        test_db.update_guest(guest_id, status='confirmed')

        # Use quota
        new_guest_id = test_db.use_quota(guest_id, "+15558888888")
        assert new_guest_id > 0

        # Verify quota was used
        guest = test_db.get_guest(guest_id)
        assert guest['quota_used'] == 1

        # Verify new guest was created
        new_guest = test_db.get_guest(new_guest_id)
        assert new_guest is not None
        assert new_guest['phone'] == "+15558888888"
        assert new_guest['invited_by_phone'] == "+15559999999"

        # Cannot use quota again
        can_invite, _ = test_db.can_invite_plus_one(guest_id)
        assert can_invite is False

        with pytest.raises(ValueError, match="Quota already used"):
            test_db.use_quota(guest_id, "+15557777777")


class TestConversationState:
    """Tests for conversation state management."""

    def test_upsert_conversation_state(self, test_db):
        """Test creating and updating conversation state."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        # Create state
        test_db.upsert_conversation_state(
            event_id,
            "+15559999999",
            "waiting_for_response",
            {"last_question": "invite"}
        )

        state = test_db.get_conversation_state(event_id, "+15559999999")
        assert state is not None
        assert state['state'] == "waiting_for_response"
        assert state['context']['last_question'] == "invite"

        # Update state
        test_db.upsert_conversation_state(
            event_id,
            "+15559999999",
            "waiting_for_name",
            {"accepted": True}
        )

        state = test_db.get_conversation_state(event_id, "+15559999999")
        assert state['state'] == "waiting_for_name"
        assert state['context']['accepted'] is True


class TestMessageLog:
    """Tests for message logging."""

    def test_log_message(self, test_db):
        """Test logging a message."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        msg_id = test_db.log_message(
            from_phone="+15551234567",
            to_phone="+15559999999",
            message_text="You're invited!",
            direction="outbound",
            event_id=event_id
        )
        assert msg_id > 0

    def test_get_recent_messages(self, test_db):
        """Test getting recent messages."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        # Log some messages
        test_db.log_message("+15551234567", "+15559999999", "Message 1", "outbound", event_id)
        test_db.log_message("+15559999999", "+15551234567", "Message 2", "inbound", event_id)
        test_db.log_message("+15551234567", "+15559999999", "Message 3", "outbound", event_id)

        messages = test_db.get_recent_messages("+15559999999", event_id, limit=10)
        assert len(messages) == 3


class TestStats:
    """Tests for event statistics."""

    def test_get_event_stats(self, test_db):
        """Test getting event statistics."""
        event_id = test_db.create_event(
            name="Test Party",
            event_date="2026-03-15",
            time_window="7-9 PM",
            location_drop_time="6:30 PM",
            rules=[],
            host_phone="+15551234567"
        )

        # Create guests with different statuses
        guest1_id = test_db.create_guest(event_id, "+15551111111")
        guest2_id = test_db.create_guest(event_id, "+15552222222")
        guest3_id = test_db.create_guest(event_id, "+15553333333")

        test_db.update_guest(guest1_id, status='confirmed')
        test_db.update_guest(guest2_id, status='confirmed')
        test_db.update_guest(guest3_id, status='declined')

        # Use quota for one guest
        test_db.use_quota(guest1_id, "+15554444444")

        stats = test_db.get_event_stats(event_id)
        assert stats['confirmed'] == 2
        assert stats['declined'] == 1
        assert stats['pending'] == 1  # The +1 invite
        assert stats['total'] == 4
        assert stats['plus_ones_used'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
