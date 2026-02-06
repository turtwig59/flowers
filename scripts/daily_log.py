"""
Daily logging utilities for human-readable conversation logs.
"""

import os
from datetime import datetime
from typing import Optional

# Default log directory
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'memory')


def ensure_log_dir():
    """Ensure log directory exists."""
    os.makedirs(LOG_DIR, exist_ok=True)


def get_today_log_path() -> str:
    """Get path to today's log file."""
    ensure_log_dir()
    today = datetime.now().strftime('%Y-%m-%d')
    return os.path.join(LOG_DIR, f'{today}.md')


def log_event(event_name: str, details: str, category: str = "Event"):
    """
    Log a significant event to today's log file.

    Args:
        event_name: Name of the event (e.g., "Invite Sent", "Guest Confirmed")
        details: Details of the event
        category: Category header (default: "Event")
    """
    ensure_log_dir()
    log_path = get_today_log_path()

    timestamp = datetime.now().strftime('%H:%M:%S')
    entry = f"\n### {timestamp} - {event_name}\n{details}\n"

    # Append to log file
    with open(log_path, 'a') as f:
        # Check if this is a new file (add header)
        if os.path.getsize(log_path) == 0 if os.path.exists(log_path) else True:
            today = datetime.now().strftime('%Y-%m-%d')
            f.write(f"# Flowers Bot - {today}\n\n")

        f.write(entry)


def log_invite_sent(event_name: str, guest_phone: str, invited_by: Optional[str] = None):
    """Log an invite being sent."""
    if invited_by:
        details = f"Sent +1 invite to {guest_phone} (invited by {invited_by})"
    else:
        details = f"Sent initial invite to {guest_phone}"

    log_event(
        "Invite Sent",
        f"**Event:** {event_name}\n**To:** {guest_phone}\n**Type:** {'Initial' if not invited_by else '+1'}",
        "Invites"
    )


def log_guest_response(event_name: str, guest_name: str, guest_phone: str, response: str):
    """Log a guest's response to invite."""
    log_event(
        f"Guest {response.title()}",
        f"**Event:** {event_name}\n**Guest:** {guest_name or guest_phone}\n**Response:** {response}",
        "Responses"
    )


def log_plus_one_used(event_name: str, guest_name: str, invited_name: str, invited_phone: str):
    """Log when a guest uses their +1 quota."""
    log_event(
        "+1 Invite Used",
        f"**Event:** {event_name}\n**By:** {guest_name}\n**Invited:** {invited_name or invited_phone}",
        "Plus Ones"
    )


def log_location_drop(event_name: str, recipient_count: int, address: str):
    """Log location drop being triggered."""
    log_event(
        "Location Drop",
        f"**Event:** {event_name}\n**Recipients:** {recipient_count} confirmed guests\n**Address:** {address}",
        "Location Drops"
    )


def log_stats_snapshot(event_name: str, stats: dict):
    """Log a statistics snapshot."""
    details = (
        f"**Event:** {event_name}\n"
        f"**Confirmed:** {stats.get('confirmed', 0)}\n"
        f"**Pending:** {stats.get('pending', 0)}\n"
        f"**Declined:** {stats.get('declined', 0)}\n"
        f"**Total:** {stats.get('total', 0)}\n"
        f"**+1s Used:** {stats.get('plus_ones_used', 0)}"
    )

    log_event(
        "Stats Snapshot",
        details,
        "Statistics"
    )


def get_today_log() -> str:
    """
    Get today's log contents.

    Returns:
        Log contents or empty string if no log today
    """
    log_path = get_today_log_path()

    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            return f.read()
    return ""


def log_custom(title: str, details: str):
    """
    Log a custom event.

    Args:
        title: Event title
        details: Event details
    """
    log_event(title, details, "Custom")
