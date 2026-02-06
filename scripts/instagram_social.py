"""
Instagram social graph logic and background worker.
Orchestrates follow -> scrape -> notify pipeline.
"""

import os
import time
import queue
import threading
import logging
from typing import Optional
from db import db

logger = logging.getLogger(__name__)

# Minimum seconds after follow before attempting rescan (30 minutes)
RESCAN_INTERVAL = 1800

# Background job queue (single worker to serialize browser access)
_job_queue = queue.Queue()
_worker_thread = None
_worker_lock = threading.Lock()


def _get_browser():
    """Get Instagram browser instance (lazy import to avoid circular deps)."""
    from instagram_browser import InstagramBrowser
    return InstagramBrowser.get_instance()


def trigger_ig_follow_and_scrape(event_id: int, guest_id: int, handle: str) -> None:
    """
    Fire-and-forget: queue a background job to follow and scrape a guest's IG.
    Called from guest_handlers.py after Instagram handle is collected.
    """
    if os.environ.get('FLOWERS_TESTING'):
        return

    handle = handle.lstrip('@').lower()

    # Record pending status
    try:
        db.upsert_ig_follow_status(event_id, guest_id, handle, 'pending')
    except Exception:
        pass

    job = {
        'event_id': event_id,
        'guest_id': guest_id,
        'handle': handle,
    }
    _job_queue.put(job)
    _ensure_worker()


def _ensure_worker():
    """Start the background worker thread if not already running."""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker_loop, daemon=True)
            _worker_thread.start()


def _worker_loop():
    """Background worker: process IG jobs one at a time, sweep for rescans on idle."""
    while True:
        try:
            job = _job_queue.get(timeout=60)
        except queue.Empty:
            _queue_pending_rescans()
            continue

        try:
            if job.get('type') == 'rescan':
                _process_rescan_job(job)
            else:
                _process_ig_job(job)
        except Exception as e:
            logger.error(f"IG job error for @{job.get('handle')}: {e}")
        finally:
            _job_queue.task_done()


def _process_ig_job(job: dict) -> None:
    """Execute: follow -> wait -> scrape -> store -> check mutual -> notify."""
    event_id = job['event_id']
    guest_id = job['guest_id']
    handle = job['handle']

    browser = _get_browser()

    # Step 1: Follow
    follow_result = browser.follow_user(handle)
    now = int(time.time())

    if follow_result == 'not_found':
        db.upsert_ig_follow_status(event_id, guest_id, handle, 'not_found',
                                   error_message='Profile not found')
        _log_follow(event_id, guest_id, handle, 'not_found')
        return

    if follow_result == 'error':
        db.upsert_ig_follow_status(event_id, guest_id, handle, 'error',
                                   error_message='Follow failed')
        _log_follow(event_id, guest_id, handle, 'error')
        return

    db.upsert_ig_follow_status(event_id, guest_id, handle, follow_result, followed_at=now)
    _log_follow(event_id, guest_id, handle, follow_result)

    # Step 2: Wait before scraping
    time.sleep(5 + __import__('random').uniform(1, 5))

    # Step 3: Scrape following list
    following = browser.scrape_following(handle)

    if following is None:
        # Private or inaccessible
        db.upsert_ig_follow_status(event_id, guest_id, handle, follow_result,
                                   scraped_at=now, following_count=0,
                                   error_message='Could not scrape (private?)')
        return

    # Step 4: Store following list
    db.store_ig_following(event_id, guest_id, handle, following)
    db.upsert_ig_follow_status(event_id, guest_id, handle, follow_result,
                               scraped_at=int(time.time()),
                               following_count=len(following))

    # Step 5: Check mutual connections and notify
    check_mutual_connections(event_id, handle, guest_id)


def _queue_pending_rescans():
    """Sweep DB for requested-but-unscraped accounts and re-queue them."""
    try:
        pending = db.get_pending_rescans(min_age_seconds=RESCAN_INTERVAL)
        for row in pending:
            job = {
                'type': 'rescan',
                'event_id': row['event_id'],
                'guest_id': row['guest_id'],
                'handle': row['handle'],
            }
            _job_queue.put(job)
        if pending:
            logger.info(f"Queued {len(pending)} IG rescans")
    except Exception as e:
        logger.error(f"Error queuing rescans: {e}")


def _process_rescan_job(job: dict) -> None:
    """Re-attempt scrape for a previously requested (private) account."""
    event_id = job['event_id']
    guest_id = job['guest_id']
    handle = job['handle']

    browser = _get_browser()
    following = browser.scrape_following(handle)

    if following is None:
        # Still private — do nothing, will retry next sweep
        return

    # Scrape succeeded — store and check mutual connections
    db.store_ig_following(event_id, guest_id, handle, following)
    db.upsert_ig_follow_status(event_id, guest_id, handle, 'requested',
                               scraped_at=int(time.time()),
                               following_count=len(following))
    check_mutual_connections(event_id, handle, guest_id)


def check_mutual_connections(event_id: int, new_handle: str, new_guest_id: int) -> list:
    """
    Find existing guests who follow the new guest and send notifications.

    Direction: existing attendee follows new person -> existing attendee gets notified.
    Returns list of (notified_guest_id, about_guest_id) pairs that were notified.
    """
    notified = []

    # Find existing guests whose following list includes the new handle
    followers = db.find_followers_of(event_id, new_handle)

    new_guest = db.get_guest(new_guest_id)
    if not new_guest:
        return notified

    new_guest_name = new_guest.get('name') or f"@{new_handle}"

    for follower in followers:
        follower_guest_id = follower['guest_id']

        # Don't notify yourself
        if follower_guest_id == new_guest_id:
            continue

        # Check for duplicate
        if db.has_notification_been_sent(event_id, follower_guest_id, new_guest_id):
            continue

        # Send notification
        msg = f"Heads up — {new_guest_name} just got on the list."
        _send_notification(follower['phone'], msg)

        # Record
        db.record_notification_sent(event_id, follower_guest_id, new_guest_id)
        _log_mutual(event_id, follower_guest_id, new_guest_id, follower.get('name'), new_guest_name)
        notified.append((follower_guest_id, new_guest_id))

    return notified


def _send_notification(phone: str, msg: str):
    """Send an iMessage notification (no-op in testing mode)."""
    if os.environ.get('FLOWERS_TESTING'):
        return
    try:
        from imsg_integration import send_imessage
        send_imessage(phone, msg)
    except Exception as e:
        logger.error(f"Failed to send IG notification to {phone}: {e}")


def _log_follow(event_id: int, guest_id: int, handle: str, result: str):
    """Log IG follow to daily log."""
    try:
        from daily_log import log_ig_follow
        log_ig_follow(event_id, handle, result)
    except Exception:
        pass


def _log_mutual(event_id: int, notified_id: int, about_id: int, notified_name: str, about_name: str):
    """Log mutual connection notification to daily log."""
    try:
        from daily_log import log_ig_mutual_connection
        log_ig_mutual_connection(notified_name or str(notified_id), about_name or str(about_id))
    except Exception:
        pass


def get_social_graph_summary(event_id: int) -> str:
    """Format the social graph for host display."""
    connections = db.get_social_graph(event_id)
    stats = db.get_ig_stats(event_id)

    if not connections and stats['with_ig'] == 0:
        return "No guests have provided Instagram handles yet."

    lines = ["Instagram Connections\n"]

    # Group by follower
    graph = {}
    for conn in connections:
        follower = conn['guest_handle']
        if follower not in graph:
            graph[follower] = []
        graph[follower].append({
            'handle': conn['follows_handle'],
            'name': conn['followed_name'],
        })

    if graph:
        for follower_handle, follows_list in sorted(graph.items()):
            lines.append(f"@{follower_handle} follows:")
            for f in follows_list:
                name_part = f" ({f['name']})" if f['name'] else ""
                lines.append(f"  -> @{f['handle']}{name_part}")
            lines.append("")

    lines.append(f"{stats['with_ig']} guests with IG | {stats['scraped']} scraped | {stats['pending']} pending")
    lines.append(f"{stats['connections']} connections between guests")

    return '\n'.join(lines)
