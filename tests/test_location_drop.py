"""
Tests for location drop functionality.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest
import tempfile
import shutil
import time
from db import Database, db as global_db
from location_drop import (
    trigger_location_drop,
    parse_location_details,
    cancel_location_drop,
    get_location_drop_preview
)
from mock_imsg import MockIMSG
from message_router import route_message
from invite_sender import send_invite


@pytest.fixture
def test_setup():
    """Set up test database and mock iMessage."""
    # Create temporary test database
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test.db')

    # Initialize schema
    from init_db import SCHEMA
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.close()

    # Replace global db with test db
    test_db = Database(db_path)
    global_db.db_path = db_path

    # Create test event
    event_id = test_db.create_event(
        name="Test Party",
        event_date="2026-03-15",
        time_window="7-9 PM",
        location_drop_time="6:30 PM",
        rules=["No photos"],
        host_phone="+12025550000"
    )

    # Create mock iMessage
    mock_imsg = MockIMSG()

    yield {
        'db': test_db,
        'event_id': event_id,
        'host_phone': "+12025550000",
        'mock_imsg': mock_imsg
    }

    # Cleanup
    shutil.rmtree(temp_dir)


class TestLocationDropTrigger:
    """Test location drop triggering."""

    def test_trigger_with_confirmed_guests(self, test_setup):
        """Test triggering location drop with confirmed guests."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        mock_imsg = test_setup['mock_imsg']

        # Create confirmed guests
        send_invite(event_id, "+12025551111")
        route_message("+12025551111", "YES", event_id)
        route_message("+12025551111", "Alice", event_id)

        send_invite(event_id, "+12025552222")
        route_message("+12025552222", "YES", event_id)
        route_message("+12025552222", "Bob", event_id)

        # Clear mock messages
        mock_imsg.clear()

        # Trigger location drop (with 1 second delay for testing)
        result = trigger_location_drop(
            event_id,
            address="123 Main St, Brooklyn NY",
            arrival_window="2-5 PM",
            notes="No photos, be cool",
            send_func=mock_imsg.send,
            delay_seconds=1
        )

        assert result['status'] == 'success'
        assert result['recipients'] == 2

        # Verify warning messages sent immediately
        assert len(mock_imsg.sent_messages) == 2
        mock_imsg.assert_sent("+12025551111", "Location drops")
        mock_imsg.assert_sent("+12025552222", "Location drops")

        # Wait for location message
        time.sleep(1.5)

        # Verify location messages sent after delay
        assert len(mock_imsg.sent_messages) == 4
        mock_imsg.assert_sent("+12025551111", "123 Main St")
        mock_imsg.assert_sent("+12025552222", "123 Main St")

    def test_trigger_with_no_confirmed_guests(self, test_setup):
        """Test triggering location drop with no confirmed guests."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        mock_imsg = test_setup['mock_imsg']

        # No confirmed guests
        result = trigger_location_drop(
            event_id,
            address="123 Main St",
            send_func=mock_imsg.send,
            delay_seconds=1
        )

        assert result['status'] == 'error'
        assert result['recipients'] == 0
        assert 'No confirmed guests' in result['message']

    def test_trigger_excludes_pending_and_declined(self, test_setup):
        """Test that location drop only goes to confirmed guests."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        mock_imsg = test_setup['mock_imsg']

        # Create guests with different statuses
        send_invite(event_id, "+12025551111")
        route_message("+12025551111", "YES", event_id)
        route_message("+12025551111", "Alice", event_id)

        send_invite(event_id, "+12025552222")  # Pending

        send_invite(event_id, "+12025553333")
        route_message("+12025553333", "NO", event_id)  # Declined

        mock_imsg.clear()

        # Trigger location drop
        result = trigger_location_drop(
            event_id,
            address="123 Main St",
            send_func=mock_imsg.send,
            delay_seconds=1
        )

        assert result['status'] == 'success'
        assert result['recipients'] == 1  # Only Alice

        # Verify only confirmed guest received message
        assert len(mock_imsg.sent_messages) == 1
        assert mock_imsg.sent_messages[0]['to'] == "+12025551111"

    def test_location_message_format(self, test_setup):
        """Test location message formatting."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        mock_imsg = test_setup['mock_imsg']

        # Create confirmed guest
        send_invite(event_id, "+12025551111")
        route_message("+12025551111", "YES", event_id)
        route_message("+12025551111", "Alice", event_id)

        mock_imsg.clear()

        # Trigger with all details
        trigger_location_drop(
            event_id,
            address="123 Main St, Brooklyn NY 11201",
            arrival_window="2-5 PM",
            notes="Ring doorbell twice",
            send_func=mock_imsg.send,
            delay_seconds=1
        )

        # Wait for location message
        time.sleep(1.5)

        # Get location message
        location_msg = mock_imsg.sent_messages[-1]['text']

        assert "123 Main St" in location_msg
        assert "2-5 PM" in location_msg
        assert "Ring doorbell twice" in location_msg
        assert "See you there" in location_msg


class TestParseLocationDetails:
    """Test location detail parsing."""

    def test_parse_full_details(self):
        """Test parsing all location details."""
        text = "123 Main St, Brooklyn | 2-5 PM | No photos, be cool"
        result = parse_location_details(text)

        assert result is not None
        assert result['address'] == "123 Main St, Brooklyn"
        assert result['arrival_window'] == "2-5 PM"
        assert result['notes'] == "No photos, be cool"

    def test_parse_address_only(self):
        """Test parsing with only address."""
        text = "123 Main St, Brooklyn"
        result = parse_location_details(text)

        assert result is not None
        assert result['address'] == "123 Main St, Brooklyn"
        assert result['arrival_window'] is None
        assert result['notes'] is None

    def test_parse_address_and_window(self):
        """Test parsing with address and arrival window."""
        text = "123 Main St | 2-5 PM"
        result = parse_location_details(text)

        assert result is not None
        assert result['address'] == "123 Main St"
        assert result['arrival_window'] == "2-5 PM"
        assert result['notes'] is None

    def test_parse_empty_fails(self):
        """Test parsing empty string fails."""
        result = parse_location_details("")
        assert result is None


class TestCancelLocationDrop:
    """Test cancelling location drops."""

    def test_cancel_before_execution(self, test_setup):
        """Test cancelling location drop before it executes."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        mock_imsg = test_setup['mock_imsg']

        # Create confirmed guest
        send_invite(event_id, "+12025551111")
        route_message("+12025551111", "YES", event_id)
        route_message("+12025551111", "Alice", event_id)

        mock_imsg.clear()

        # Trigger location drop with delay
        result = trigger_location_drop(
            event_id,
            address="123 Main St",
            send_func=mock_imsg.send,
            delay_seconds=2
        )

        timer = result['timer']

        # Warning sent immediately
        assert len(mock_imsg.sent_messages) == 1

        # Cancel before location message
        cancelled = cancel_location_drop(timer)
        assert cancelled is True

        # Wait past the delay
        time.sleep(2.5)

        # Location message should not have been sent
        assert len(mock_imsg.sent_messages) == 1  # Still just the warning


class TestLocationDropPreview:
    """Test location drop preview."""

    def test_preview_messages(self, test_setup):
        """Test previewing location drop messages."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        # Create confirmed guests
        send_invite(event_id, "+12025551111")
        route_message("+12025551111", "YES", event_id)
        route_message("+12025551111", "Alice", event_id)

        send_invite(event_id, "+12025552222")
        route_message("+12025552222", "YES", event_id)
        route_message("+12025552222", "Bob", event_id)

        # Get preview
        preview = get_location_drop_preview(
            event_id,
            address="123 Main St",
            arrival_window="2-5 PM",
            notes="Be cool"
        )

        assert preview['recipients'] == 2
        assert "Alice" in preview['recipient_names']
        assert "Bob" in preview['recipient_names']
        assert "Location drops in 5 minutes" in preview['warning_message']
        assert "123 Main St" in preview['location_message']
        assert "2-5 PM" in preview['location_message']
        assert "Be cool" in preview['location_message']


class TestHostLocationDropFlow:
    """Test full host location drop flow via message routing."""

    def test_host_drop_location_command(self, test_setup):
        """Test host requesting location drop."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        host_phone = test_setup['host_phone']

        # Create confirmed guest
        send_invite(event_id, "+12025551111")
        route_message("+12025551111", "YES", event_id)
        route_message("+12025551111", "Alice", event_id)

        # Host requests drop
        response = route_message(host_phone, "drop location", event_id)
        assert "Ready to drop" in response
        assert "1 confirmed guests" in response
        assert "|" in response  # Instructions mention pipe format

    def test_host_send_location_details(self, test_setup):
        """Test host sending location details."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        host_phone = test_setup['host_phone']

        # Create confirmed guest
        send_invite(event_id, "+12025551111")
        route_message("+12025551111", "YES", event_id)
        route_message("+12025551111", "Alice", event_id)

        # Host sends location details
        response = route_message(
            host_phone,
            "123 Main St, Brooklyn | 2-5 PM | No photos",
            event_id
        )

        # Verify response confirms drop initiated
        assert "Location drop initiated" in response
        assert "1 confirmed guests" in response
        assert "123 Main St" in response

        # Verify messages were logged in database
        messages = db.get_recent_messages("+12025551111", event_id, limit=10)
        location_messages = [m for m in messages if "Location drops" in m['message_text']]
        assert len(location_messages) >= 1  # At least the warning message


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
