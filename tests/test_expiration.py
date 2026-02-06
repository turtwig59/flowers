"""
Tests for invite and +1 expiration timers.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest
import tempfile
import shutil
import time
from db import Database, db as global_db
from message_router import route_message
from invite_sender import send_invite
import expiration_checker
from expiration_checker import (
    check_invite_expirations,
    check_plus_one_expirations,
    INVITE_WARNING_SECONDS,
    INVITE_EXPIRE_SECONDS,
    PLUS_ONE_WARNING_SECONDS,
    PLUS_ONE_EXPIRE_SECONDS,
)

# Disable deploy-time cutoff in tests so backdated timestamps work
expiration_checker.FEATURE_DEPLOY_TIME = 0


@pytest.fixture
def test_setup():
    """Set up test database."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test.db')

    from init_db import SCHEMA
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.close()

    test_db = Database(db_path)
    global_db.db_path = db_path

    event_id = test_db.create_event(
        name="Test Party",
        event_date="2026-03-15",
        time_window="7-9 PM",
        location_drop_time="6:30 PM",
        rules=["No photos"],
        host_phone="+12025550000"
    )

    yield {
        'db': test_db,
        'event_id': event_id,
        'host_phone': "+12025550000",
    }

    shutil.rmtree(temp_dir)


def _set_invited_at(db, guest_id, seconds_ago):
    """Helper to backdate a guest's invited_at timestamp."""
    new_time = int(time.time()) - seconds_ago
    with db.transaction() as conn:
        conn.execute("UPDATE guests SET invited_at = ? WHERE id = ?", (new_time, guest_id))


def _set_responded_at(db, guest_id, seconds_ago):
    """Helper to backdate a guest's responded_at timestamp."""
    new_time = int(time.time()) - seconds_ago
    with db.transaction() as conn:
        conn.execute("UPDATE guests SET responded_at = ? WHERE id = ?", (new_time, guest_id))


class TestInviteExpiration:
    """Tests for invite acceptance time limit."""

    def test_no_action_before_warning(self, test_setup):
        """No warning or expiry if invite is less than 45 minutes old."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551001"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)

        # Set invited_at to 30 minutes ago
        _set_invited_at(db, guest['id'], 1800)

        check_invite_expirations()

        # Should still be pending
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['status'] == 'pending'

        # No warning flag set
        state = db.get_conversation_state(event_id, phone)
        assert not state['context'].get('invite_warning_sent')

    def test_warning_sent_at_45_minutes(self, test_setup):
        """Warning is sent when invite is 45+ minutes old."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551002"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)

        # Set invited_at to 46 minutes ago (past warning threshold)
        _set_invited_at(db, guest['id'], INVITE_WARNING_SECONDS + 60)

        check_invite_expirations()

        # Still pending (not expired yet)
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['status'] == 'pending'

        # Warning flag should be set
        state = db.get_conversation_state(event_id, phone)
        assert state['context'].get('invite_warning_sent') is True

    def test_warning_sent_only_once(self, test_setup):
        """Warning is idempotent — only sent once."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551003"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)
        _set_invited_at(db, guest['id'], INVITE_WARNING_SECONDS + 60)

        # Run twice
        check_invite_expirations()
        check_invite_expirations()

        # Flag should still be True (idempotent)
        state = db.get_conversation_state(event_id, phone)
        assert state['context'].get('invite_warning_sent') is True
        # Guest still pending
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['status'] == 'pending'

    def test_expired_at_60_minutes(self, test_setup):
        """Invite expires after 60 minutes."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551004"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)
        _set_invited_at(db, guest['id'], INVITE_EXPIRE_SECONDS + 60)

        check_invite_expirations()

        # Should be expired
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['status'] == 'expired'

        # State should be idle
        state = db.get_conversation_state(event_id, phone)
        assert state['state'] == 'idle'
        assert state['context'].get('expired') is True

    def test_no_expiry_if_already_responded(self, test_setup):
        """Don't expire if guest already accepted."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551005"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)

        # Guest accepts
        route_message(phone, "YES", event_id)

        # Backdate invited_at past expiry
        _set_invited_at(db, guest['id'], INVITE_EXPIRE_SECONDS + 60)

        check_invite_expirations()

        # Should still be confirmed (not expired)
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['status'] == 'confirmed'

    def test_race_condition_respond_same_cycle(self, test_setup):
        """Guest responds between query and expiry check — should not expire."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551006"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)
        _set_invited_at(db, guest['id'], INVITE_EXPIRE_SECONDS + 60)

        # Simulate: guest responds right before expiry check reads fresh data
        route_message(phone, "YES", event_id)

        check_invite_expirations()

        # Should be confirmed, not expired
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['status'] == 'confirmed'

    def test_expired_guest_blocked_from_messaging(self, test_setup):
        """Expired guest is blocked from all interaction via message_router."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551007"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)
        _set_invited_at(db, guest['id'], INVITE_EXPIRE_SECONDS + 60)

        check_invite_expirations()

        # Try to message
        response = route_message(phone, "YES", event_id)
        assert "expired" in response.lower()

        # Still expired
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['status'] == 'expired'

    def test_expired_guest_handler_guard(self, test_setup):
        """handle_invite_response returns expired message if guest is expired."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025551008"

        send_invite(event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)

        # Manually expire
        db.update_guest(guest['id'], status='expired')

        from guest_handlers import handle_invite_response
        response = handle_invite_response(
            db.get_guest_by_phone(phone, event_id), "YES", event_id
        )
        assert "expired" in response.lower()


class TestPlusOneExpiration:
    """Tests for +1 invite window time limit."""

    def _accept_and_complete_onboarding(self, db, event_id, phone):
        """Helper: accept invite and complete onboarding to get to idle state."""
        send_invite(event_id, phone)
        route_message(phone, "YES", event_id)
        route_message(phone, "TestName", event_id)
        route_message(phone, "skip", event_id)  # Skip Instagram
        route_message(phone, "NO", event_id)     # Decline +1 for now
        return db.get_guest_by_phone(phone, event_id)

    def test_no_action_before_warning(self, test_setup):
        """No warning if responded_at is less than 45 minutes ago."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552001"

        self._accept_and_complete_onboarding(db, event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)

        # Set responded_at to 30 minutes ago
        _set_responded_at(db, guest['id'], 1800)

        check_plus_one_expirations()

        # Quota should still be 0
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 0

    def test_warning_sent_at_45_minutes(self, test_setup):
        """Warning sent when +1 window is 45+ minutes old."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552002"

        self._accept_and_complete_onboarding(db, event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)
        _set_responded_at(db, guest['id'], PLUS_ONE_WARNING_SECONDS + 60)

        check_plus_one_expirations()

        # Quota still 0
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 0

        # Warning flag set
        state = db.get_conversation_state(event_id, phone)
        assert state['context'].get('plus_one_warning_sent') is True

    def test_warning_sent_only_once(self, test_setup):
        """Warning is idempotent."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552003"

        self._accept_and_complete_onboarding(db, event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)
        _set_responded_at(db, guest['id'], PLUS_ONE_WARNING_SECONDS + 60)

        check_plus_one_expirations()
        check_plus_one_expirations()

        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 0

    def test_expired_at_60_minutes(self, test_setup):
        """Invites revoked after 60 minutes."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552004"

        self._accept_and_complete_onboarding(db, event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)
        _set_responded_at(db, guest['id'], PLUS_ONE_EXPIRE_SECONDS + 60)

        check_plus_one_expirations()

        # Quota should be set to 2 (revoked)
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 2

        # State should be idle
        state = db.get_conversation_state(event_id, phone)
        assert state['state'] == 'idle'

    def test_no_expiry_if_quota_already_used(self, test_setup):
        """Don't expire if guest already used both invites."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552005"

        send_invite(event_id, phone)
        route_message(phone, "YES", event_id)
        route_message(phone, "TestName", event_id)
        route_message(phone, "skip", event_id)

        # Use both invites
        route_message(phone, "YES", event_id)
        route_message(phone, "+12025559901", event_id)
        route_message(phone, "+12025559902", event_id)

        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 2

        # Backdate and run — should be a no-op
        _set_responded_at(db, guest['id'], PLUS_ONE_EXPIRE_SECONDS + 60)
        check_plus_one_expirations()

        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 2
        assert guest['status'] == 'confirmed'

    def test_silent_revocation_during_onboarding(self, test_setup):
        """If guest is still in onboarding (waiting_for_name/instagram), silently revoke."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552006"

        send_invite(event_id, phone)
        route_message(phone, "YES", event_id)
        # Guest is now in waiting_for_name — hasn't finished onboarding

        guest = db.get_guest_by_phone(phone, event_id)
        _set_responded_at(db, guest['id'], PLUS_ONE_EXPIRE_SECONDS + 60)

        check_plus_one_expirations()

        # Quota revoked silently
        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 2

        # State should NOT have changed (still in onboarding)
        state = db.get_conversation_state(event_id, phone)
        assert state['state'] == 'waiting_for_name'

    def test_no_warning_during_onboarding(self, test_setup):
        """No warning sent while guest is still in onboarding."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552007"

        send_invite(event_id, phone)
        route_message(phone, "YES", event_id)
        # Guest is in waiting_for_name

        guest = db.get_guest_by_phone(phone, event_id)
        _set_responded_at(db, guest['id'], PLUS_ONE_WARNING_SECONDS + 60)

        check_plus_one_expirations()

        # No warning flag
        state = db.get_conversation_state(event_id, phone)
        assert not state['context'].get('plus_one_warning_sent')

    def test_plus_one_handler_guard(self, test_setup):
        """handle_plus_one_offer returns closed message if quota revoked."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552008"

        self._accept_and_complete_onboarding(db, event_id, phone)
        guest = db.get_guest_by_phone(phone, event_id)

        # Manually set quota to 2 (as expiration would)
        db.update_guest(guest['id'], quota_used=2)

        from guest_handlers import handle_plus_one_offer
        guest = db.get_guest_by_phone(phone, event_id)
        response = handle_plus_one_offer(guest, "YES", event_id)
        assert "closed" in response.lower() or "event" in response.lower()

    def test_expiry_during_waiting_for_contact(self, test_setup):
        """If guest is in waiting_for_contact state when +1 expires, they get a message."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025552009"

        send_invite(event_id, phone)
        route_message(phone, "YES", event_id)
        route_message(phone, "TestName", event_id)
        route_message(phone, "skip", event_id)
        route_message(phone, "YES", event_id)  # wants to invite → waiting_for_contact

        state = db.get_conversation_state(event_id, phone)
        assert state['state'] == 'waiting_for_contact'

        guest = db.get_guest_by_phone(phone, event_id)
        _set_responded_at(db, guest['id'], PLUS_ONE_EXPIRE_SECONDS + 60)

        check_plus_one_expirations()

        guest = db.get_guest_by_phone(phone, event_id)
        assert guest['quota_used'] == 2

        state = db.get_conversation_state(event_id, phone)
        assert state['state'] == 'idle'


class TestMergeConversationContext:
    """Test the merge_conversation_context helper."""

    def test_merge_preserves_existing_keys(self, test_setup):
        """Merging new keys doesn't remove existing ones."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025553001"

        db.upsert_conversation_state(event_id, phone, 'waiting_for_response',
                                     {'invite_sent_at': '2026-01-01', 'foo': 'bar'})

        db.merge_conversation_context(event_id, phone, {'invite_warning_sent': True})

        state = db.get_conversation_state(event_id, phone)
        assert state['context']['foo'] == 'bar'
        assert state['context']['invite_sent_at'] == '2026-01-01'
        assert state['context']['invite_warning_sent'] is True

    def test_merge_overwrites_existing_key(self, test_setup):
        """Merging an existing key overwrites its value."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        phone = "+12025553002"

        db.upsert_conversation_state(event_id, phone, 'idle', {'count': 1})
        db.merge_conversation_context(event_id, phone, {'count': 2})

        state = db.get_conversation_state(event_id, phone)
        assert state['context']['count'] == 2
