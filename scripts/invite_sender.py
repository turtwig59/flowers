"""
Invite sending utilities.
Handles sending invites via iMessage and logging.
"""

import os
from typing import Optional
from db import db
from datetime import datetime
from daily_log import log_invite_sent


def format_date(iso_date: str) -> str:
    """
    Format ISO date to human-readable format.

    Args:
        iso_date: Date in ISO format (YYYY-MM-DD)

    Returns:
        Formatted date (e.g., "Saturday, March 15")
    """
    try:
        date_obj = datetime.fromisoformat(iso_date)
        return date_obj.strftime("%A, %B %d")
    except:
        return iso_date


def send_invite(
    event_id: int,
    to_phone: str,
    invited_by_phone: Optional[str] = None,
    imsg_send_func = None
) -> str:
    """
    Send invitation message via iMessage.

    Args:
        event_id: Event ID
        to_phone: Recipient phone number (E.164)
        invited_by_phone: Phone of person inviting (None for initial invites)
        imsg_send_func: Function to send iMessage (for testing, uses mock if None)

    Returns:
        Message text sent
    """
    event = db.get_event(event_id)

    INTRO = "I'm Yed - a text-only doorman. Someone put you on the list."

    # Different message based on invite source
    if invited_by_phone:
        # +1 invite
        inviter = db.get_guest_by_phone(invited_by_phone, event_id)
        inviter_name = inviter['name'] if inviter and inviter['name'] else "Someone"

        message = (
            f"{INTRO}\n\n"
            f"{inviter_name} invited you to {event['name']} "
            f"on {format_date(event['event_date'])}, {event['time_window']}.\n\n"
            f"Let me know if you'd like to come."
        )
    else:
        # Initial invite (from host)
        message = (
            f"{INTRO}\n\n"
            f"Rishab invited you to {event['name']} "
            f"on {format_date(event['event_date'])}, {event['time_window']}.\n\n"
            f"Let me know if you'd like to come."
        )

    # Send via iMessage
    if imsg_send_func:
        imsg_send_func(to_phone, message)
    elif os.environ.get('FLOWERS_TESTING'):
        pass  # Skip sending in test mode
    else:
        from imsg_integration import send_imessage
        send_imessage(to_phone, message)

    # Log message
    db.log_message(
        from_phone=event['host_phone'],
        to_phone=to_phone,
        message_text=message,
        direction='outbound',
        event_id=event_id
    )

    # Ensure guest record exists
    existing = db.get_guest_by_phone(to_phone, event_id)
    if not existing:
        db.create_guest(event_id, to_phone, invited_by_phone)

    # Set conversation state to waiting for response
    db.upsert_conversation_state(
        event_id,
        to_phone,
        'waiting_for_response',
        {'invite_sent_at': datetime.now().isoformat()}
    )

    # Log to daily log
    try:
        inviter_name = None
        if invited_by_phone:
            inviter = db.get_guest_by_phone(invited_by_phone, event_id)
            inviter_name = inviter['name'] if inviter and inviter['name'] else invited_by_phone
        log_invite_sent(event['name'], to_phone, inviter_name)
    except:
        pass  # Logging errors shouldn't break functionality

    return message
