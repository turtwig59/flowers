"""
Location drop orchestration.
Handles the two-part location reveal ritual with timing.
"""

import os
import threading
import time
from typing import Optional, Callable
from db import db
from daily_log import log_location_drop


def trigger_location_drop(
    event_id: int,
    address: str,
    arrival_window: Optional[str] = None,
    notes: Optional[str] = None,
    send_func: Optional[Callable] = None,
    delay_seconds: int = 300  # 5 minutes default
) -> dict:
    """
    Trigger location drop to all confirmed guests.

    Sends two-part message:
    1. "Location drops in 5 minutes" → send immediately
    2. (5 minutes later) actual location

    Args:
        event_id: Event ID
        address: Full address to reveal
        arrival_window: Optional arrival window (e.g., "2-5 PM")
        notes: Optional last notes (e.g., "No photos, be cool")
        send_func: Function to send messages (for testing, uses mock if None)
        delay_seconds: Delay between messages (default 300 = 5 minutes)

    Returns:
        Dict with status and recipient count
    """
    event = db.get_event(event_id)
    confirmed_guests = db.get_guests(event_id, status='confirmed')

    if not confirmed_guests:
        return {
            'status': 'error',
            'message': 'No confirmed guests to send location to',
            'recipients': 0
        }

    # Get send function
    if send_func is None:
        if os.environ.get('FLOWERS_TESTING'):
            send_func = lambda to, text: None  # No-op in test mode
        else:
            from imsg_integration import send_imessage
            send_func = send_imessage

    # Part 1: Warning message
    warning_message = (
        f"🎉 {event['name']}\n\n"
        f"Location drops in {delay_seconds // 60} minutes.\n"
        f"Get ready!"
    )

    for guest in confirmed_guests:
        send_func(guest['phone'], warning_message)
        db.log_message(
            from_phone=event['host_phone'],
            to_phone=guest['phone'],
            message_text=warning_message,
            direction='outbound',
            event_id=event_id
        )

    # Part 2: Schedule actual location drop
    def send_location():
        """Send actual location after delay."""
        # Build location message
        location_parts = [f"📍 {event['name']}\n"]

        # Add address
        location_parts.append(f"{address}\n")

        # Add arrival window if provided
        if arrival_window:
            location_parts.append(f"Arrival: {arrival_window}\n")

        # Add notes if provided
        if notes:
            location_parts.append(f"\n{notes}\n")

        # Add closing
        location_parts.append("\nSee you there!")

        location_message = '\n'.join(location_parts)

        # Send to all confirmed guests
        for guest in confirmed_guests:
            send_func(guest['phone'], location_message)
            db.log_message(
                from_phone=event['host_phone'],
                to_phone=guest['phone'],
                message_text=location_message,
                direction='outbound',
                event_id=event_id
            )

    # Schedule the location message
    timer = threading.Timer(delay_seconds, send_location)
    timer.daemon = True  # Allow program to exit even if timer pending
    timer.start()

    # Log location drop
    try:
        log_location_drop(event['name'], len(confirmed_guests), address)
    except:
        pass

    return {
        'status': 'success',
        'message': f'Location drop initiated to {len(confirmed_guests)} confirmed guests',
        'recipients': len(confirmed_guests),
        'timer': timer  # Return timer for testing (can be cancelled)
    }


def parse_location_details(text: str) -> Optional[dict]:
    """
    Parse location drop details from host message.

    Expected format:
        [address] | [arrival window] | [notes]

    Args:
        text: Host message with location details

    Returns:
        Dict with address, arrival_window, notes or None if parse fails
    """
    # Split by pipe
    parts = [p.strip() for p in text.split('|')]

    if len(parts) < 1:
        return None

    result = {
        'address': parts[0] if len(parts) > 0 else None,
        'arrival_window': parts[1] if len(parts) > 1 else None,
        'notes': parts[2] if len(parts) > 2 else None
    }

    # Address is required
    if not result['address']:
        return None

    return result


def cancel_location_drop(timer: threading.Timer) -> bool:
    """
    Cancel a scheduled location drop.

    Args:
        timer: Timer object returned from trigger_location_drop

    Returns:
        True if cancelled successfully
    """
    if timer and timer.is_alive():
        timer.cancel()
        return True
    return False


def get_location_drop_preview(
    event_id: int,
    address: str,
    arrival_window: Optional[str] = None,
    notes: Optional[str] = None
) -> dict:
    """
    Preview what will be sent without actually sending.

    Args:
        event_id: Event ID
        address: Address
        arrival_window: Optional arrival window
        notes: Optional notes

    Returns:
        Dict with preview messages and recipient info
    """
    event = db.get_event(event_id)
    confirmed_guests = db.get_guests(event_id, status='confirmed')

    # Build warning message
    warning_message = (
        f"🎉 {event['name']}\n\n"
        f"Location drops in 5 minutes.\n"
        f"Get ready!"
    )

    # Build location message
    location_parts = [f"📍 {event['name']}\n"]
    location_parts.append(f"{address}\n")

    if arrival_window:
        location_parts.append(f"Arrival: {arrival_window}\n")

    if notes:
        location_parts.append(f"\n{notes}\n")

    location_parts.append("\nSee you there!")
    location_message = '\n'.join(location_parts)

    return {
        'recipients': len(confirmed_guests),
        'recipient_names': [g['name'] or g['phone'] for g in confirmed_guests],
        'warning_message': warning_message,
        'location_message': location_message
    }
