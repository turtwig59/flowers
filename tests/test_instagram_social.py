"""
Tests for Instagram social graph feature.
Tests mutual connections, notifications, graph command, and edge cases.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest
import tempfile
import shutil
import sqlite3
from unittest.mock import patch, MagicMock
from db import Database, db as global_db
from init_db import SCHEMA
from mock_instagram import MockInstagramBrowser


@pytest.fixture
def test_setup():
    """Set up test database with IG tables and mock browser."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test.db')

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.close()

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

    # Create mock browser
    mock_browser = MockInstagramBrowser()

    yield {
        'db': test_db,
        'event_id': event_id,
        'host_phone': "+12025550000",
        'mock_browser': mock_browser,
        'temp_dir': temp_dir,
    }

    shutil.rmtree(temp_dir)


def _create_guest(db, event_id, phone, name=None, instagram=None, status='confirmed'):
    """Helper to create a guest with optional fields."""
    guest_id = db.create_guest(event_id, phone)
    updates = {}
    if name:
        updates['name'] = name
    if instagram:
        updates['instagram'] = instagram
    if status != 'pending':
        updates['status'] = status
    if updates:
        db.update_guest(guest_id, **updates)
    return guest_id


class TestMutualConnectionNotification:
    """Test that existing guests get notified when someone they follow joins."""

    def test_mutual_connection_sends_notification(self, test_setup):
        """When Guest A follows Guest B's handle, A gets notified when B joins."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        # Guest A: alice, already confirmed, follows bob_smith on IG
        alice_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")

        # Store Alice's following list (she follows bob_smith)
        db.store_ig_following(event_id, alice_id, "alice_nyc", ["bob_smith", "charlie_d", "random_person"])

        # Guest B: bob, just joined
        bob_id = _create_guest(db, event_id, "+12025552222", name="Bob", instagram="@bob_smith")

        # Check mutual connections for bob
        from instagram_social import check_mutual_connections
        notified = check_mutual_connections(event_id, "bob_smith", bob_id)

        # Alice should be notified about Bob
        assert len(notified) == 1
        assert notified[0] == (alice_id, bob_id)

        # Notification should be recorded
        assert db.has_notification_been_sent(event_id, alice_id, bob_id)

    def test_no_duplicate_notifications(self, test_setup):
        """Same notification should not be sent twice."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        alice_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")
        db.store_ig_following(event_id, alice_id, "alice_nyc", ["bob_smith"])

        bob_id = _create_guest(db, event_id, "+12025552222", name="Bob", instagram="@bob_smith")

        from instagram_social import check_mutual_connections

        # First check
        notified1 = check_mutual_connections(event_id, "bob_smith", bob_id)
        assert len(notified1) == 1

        # Second check — should not re-notify
        notified2 = check_mutual_connections(event_id, "bob_smith", bob_id)
        assert len(notified2) == 0

    def test_no_self_notification(self, test_setup):
        """Guest should not be notified about themselves."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        alice_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")
        # Alice follows her own handle (edge case)
        db.store_ig_following(event_id, alice_id, "alice_nyc", ["alice_nyc"])

        from instagram_social import check_mutual_connections
        notified = check_mutual_connections(event_id, "alice_nyc", alice_id)
        assert len(notified) == 0

    def test_multiple_followers_notified(self, test_setup):
        """Multiple guests who follow the new person all get notified."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        alice_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")
        charlie_id = _create_guest(db, event_id, "+12025553333", name="Charlie", instagram="@charlie_d")

        # Both Alice and Charlie follow bob_smith
        db.store_ig_following(event_id, alice_id, "alice_nyc", ["bob_smith"])
        db.store_ig_following(event_id, charlie_id, "charlie_d", ["bob_smith"])

        bob_id = _create_guest(db, event_id, "+12025552222", name="Bob", instagram="@bob_smith")

        from instagram_social import check_mutual_connections
        notified = check_mutual_connections(event_id, "bob_smith", bob_id)

        assert len(notified) == 2
        notified_ids = {n[0] for n in notified}
        assert alice_id in notified_ids
        assert charlie_id in notified_ids


class TestPrivateAndInvalidAccounts:
    """Test handling of private accounts and invalid handles."""

    def test_private_account_gracefully_skipped(self, test_setup):
        """Private account scrape returns None, no crash."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        mock_browser = test_setup['mock_browser']

        guest_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")

        # Mock browser returns None for scraping (private)
        assert mock_browser.scrape_following("alice_nyc") is None

        # Follow status can still be recorded
        db.upsert_ig_follow_status(event_id, guest_id, "alice_nyc", "requested",
                                   error_message="Could not scrape (private?)")
        status = db.get_ig_follow_status(event_id, guest_id)
        assert status['status'] == 'requested'
        assert 'private' in status['error_message']

    def test_not_found_handle_recorded(self, test_setup):
        """Invalid handle gets recorded as not_found."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        mock_browser = test_setup['mock_browser']

        guest_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@nonexistent")
        mock_browser.set_follow_result("nonexistent", "not_found")

        result = mock_browser.follow_user("nonexistent")
        assert result == 'not_found'

        db.upsert_ig_follow_status(event_id, guest_id, "nonexistent", "not_found",
                                   error_message="Profile not found")
        status = db.get_ig_follow_status(event_id, guest_id)
        assert status['status'] == 'not_found'


class TestIGFollowStatus:
    """Test IG follow status tracking in DB."""

    def test_upsert_follow_status(self, test_setup):
        """Test creating and updating follow status."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        guest_id = _create_guest(db, event_id, "+12025551111")

        # Initial insert
        db.upsert_ig_follow_status(event_id, guest_id, "alice_nyc", "pending")
        status = db.get_ig_follow_status(event_id, guest_id)
        assert status['status'] == 'pending'
        assert status['handle'] == 'alice_nyc'

        # Update to followed
        db.upsert_ig_follow_status(event_id, guest_id, "alice_nyc", "followed", followed_at=1000)
        status = db.get_ig_follow_status(event_id, guest_id)
        assert status['status'] == 'followed'
        assert status['followed_at'] == 1000

    def test_store_and_query_following(self, test_setup):
        """Test storing and querying following lists."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        guest_id = _create_guest(db, event_id, "+12025551111", instagram="@alice_nyc")
        db.store_ig_following(event_id, guest_id, "alice_nyc", ["bob_smith", "charlie_d"])

        # Query: who follows bob_smith?
        followers = db.find_followers_of(event_id, "bob_smith")
        assert len(followers) == 1
        assert followers[0]['guest_id'] == guest_id

    def test_case_insensitive_following(self, test_setup):
        """Following lookups should be case-insensitive."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        guest_id = _create_guest(db, event_id, "+12025551111", instagram="@alice_nyc")
        db.store_ig_following(event_id, guest_id, "alice_nyc", ["Bob_Smith"])

        # Query with lowercase
        followers = db.find_followers_of(event_id, "bob_smith")
        assert len(followers) == 1


class TestHostGraphCommand:
    """Test the host 'graph' command output."""

    def test_graph_with_connections(self, test_setup):
        """Test graph output when connections exist."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        alice_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")
        bob_id = _create_guest(db, event_id, "+12025552222", name="Bob", instagram="@bob_smith")

        db.store_ig_following(event_id, alice_id, "alice_nyc", ["bob_smith"])

        from instagram_social import get_social_graph_summary
        output = get_social_graph_summary(event_id)

        assert "@alice_nyc follows:" in output
        assert "@bob_smith" in output
        assert "Bob" in output

    def test_graph_empty(self, test_setup):
        """Test graph when no IG handles exist."""
        event_id = test_setup['event_id']

        from instagram_social import get_social_graph_summary
        output = get_social_graph_summary(event_id)

        assert "No guests have provided Instagram handles" in output

    def test_graph_with_ig_but_no_connections(self, test_setup):
        """Test graph when guests have IG but no mutual connections."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")

        from instagram_social import get_social_graph_summary
        output = get_social_graph_summary(event_id)

        assert "1 guests with IG" in output
        assert "0 connections" in output

    def test_graph_via_host_message(self, test_setup):
        """Test graph command through message routing."""
        db = test_setup['db']
        event_id = test_setup['event_id']
        host_phone = test_setup['host_phone']

        from message_router import route_message
        response = route_message(host_phone, "graph", event_id)
        assert "Instagram" in response or "No guests" in response


class TestTestingModeNoOps:
    """Verify FLOWERS_TESTING=1 causes no real operations."""

    def test_trigger_is_noop_in_testing(self, test_setup):
        """trigger_ig_follow_and_scrape should be a no-op when FLOWERS_TESTING=1."""
        # FLOWERS_TESTING is already set by conftest.py
        from instagram_social import trigger_ig_follow_and_scrape, _job_queue

        initial_qsize = _job_queue.qsize()
        trigger_ig_follow_and_scrape(1, 1, "test_handle")

        # Should not have queued a job
        assert _job_queue.qsize() == initial_qsize

    def test_browser_follow_noop(self):
        """InstagramBrowser.follow_user returns 'followed' in testing mode."""
        from instagram_browser import InstagramBrowser
        browser = InstagramBrowser()
        result = browser.follow_user("test_handle")
        assert result == 'followed'

    def test_browser_scrape_noop(self):
        """InstagramBrowser.scrape_following returns [] in testing mode."""
        from instagram_browser import InstagramBrowser
        browser = InstagramBrowser()
        result = browser.scrape_following("test_handle")
        assert result == []


class TestIGStats:
    """Test Instagram statistics queries."""

    def test_ig_stats(self, test_setup):
        """Test get_ig_stats returns correct counts."""
        db = test_setup['db']
        event_id = test_setup['event_id']

        alice_id = _create_guest(db, event_id, "+12025551111", name="Alice", instagram="@alice_nyc")
        bob_id = _create_guest(db, event_id, "+12025552222", name="Bob", instagram="@bob_smith")
        _create_guest(db, event_id, "+12025553333", name="Charlie")  # No IG

        # Alice: fully scraped
        db.upsert_ig_follow_status(event_id, alice_id, "alice_nyc", "followed", scraped_at=1000)
        db.store_ig_following(event_id, alice_id, "alice_nyc", ["bob_smith"])

        # Bob: pending
        db.upsert_ig_follow_status(event_id, bob_id, "bob_smith", "pending")

        stats = db.get_ig_stats(event_id)
        assert stats['with_ig'] == 2
        assert stats['scraped'] == 1
        assert stats['pending'] == 1
        assert stats['connections'] == 1  # alice follows bob


class TestMockBrowser:
    """Test the mock browser itself."""

    def test_mock_follow_default(self):
        mock = MockInstagramBrowser()
        assert mock.follow_user("someone") == 'followed'

    def test_mock_follow_custom(self):
        mock = MockInstagramBrowser()
        mock.set_follow_result("private_user", "requested")
        assert mock.follow_user("private_user") == 'requested'

    def test_mock_scrape_with_data(self):
        mock = MockInstagramBrowser()
        mock.set_following("alice", ["bob", "charlie"])
        result = mock.scrape_following("alice")
        assert "bob" in result
        assert "charlie" in result

    def test_mock_scrape_private(self):
        mock = MockInstagramBrowser()
        result = mock.scrape_following("unknown_user")
        assert result is None

    def test_mock_tracks_calls(self):
        mock = MockInstagramBrowser()
        mock.follow_user("a")
        mock.follow_user("b")
        mock.scrape_following("a")
        assert mock.follow_calls == ["a", "b"]
        assert mock.scrape_calls == ["a"]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
