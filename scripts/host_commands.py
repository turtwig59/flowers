"""
Host command handlers for event management.
"""

import os
from typing import Optional, List
from db import db
from phone_utils import mask_phone, extract_phone_from_text, normalize_phone
from message_router import detect_host_command
from invite_sender import send_invite
from location_drop import trigger_location_drop, parse_location_details, get_location_drop_preview
from event_creation import (
    get_host_event_creation_state,
    start_event_creation,
    handle_event_creation_message
)


def get_status_emoji(status: str) -> str:
    """Get emoji for guest status."""
    return {
        'confirmed': '✅',
        'pending': '⏳',
        'declined': '❌',
        'expired': '⏰'
    }.get(status, '❓')


def format_guest_list(event_id: int, style: str = 'tree') -> str:
    """
    Format guest list for host.

    Args:
        event_id: Event ID
        style: Display style ('tree', 'simple', 'stats')

    Returns:
        Formatted guest list
    """
    event = db.get_event(event_id)
    guests = db.get_guests(event_id)

    if style == 'stats':
        stats = db.get_event_stats(event_id)
        lines = [
            f"📊 {event['name']}\n",
            f"✅ Confirmed: {stats['confirmed']}",
            f"⏳ Pending: {stats['pending']}",
            f"❌ Declined: {stats['declined']}",
        ]
        expired = stats.get('expired', 0)
        if expired > 0:
            lines.append(f"⏰ Expired: {expired}")
        lines.append(f"📥 Total invited: {stats['total']}")
        lines.append(f"➕ +1s used: {stats['plus_ones_used']}")
        return '\n'.join(lines)

    elif style == 'simple':
        confirmed = [g for g in guests if g['status'] == 'confirmed']
        if not confirmed:
            return f"📋 {event['name']}\n\nNo confirmed guests yet."

        lines = [f"✅ Confirmed ({len(confirmed)}):"]
        for g in confirmed:
            name = g['name'] or mask_phone(g['phone'])
            lines.append(f"  • {name}")
        return '\n'.join(lines)

    elif style == 'tree':
        # Build invite tree
        initial_invites = [g for g in guests if not g['invited_by_phone']]

        if not initial_invites:
            return f"📋 {event['name']}\n\nNo guests invited yet."

        lines = [f"📋 {event['name']}\n"]

        for initial in initial_invites:
            # Show initial invite
            name = initial['name'] or mask_phone(initial['phone'])
            status_icon = get_status_emoji(initial['status'])
            lines.append(f"{status_icon} {name}")

            # Show their +1 if any
            plus_ones = [g for g in guests if g['invited_by_phone'] == initial['phone']]
            for plus_one in plus_ones:
                po_name = plus_one['name'] or mask_phone(plus_one['phone'])
                po_status = get_status_emoji(plus_one['status'])
                lines.append(f"  └─ {po_status} {po_name}")

        return '\n'.join(lines)

    else:
        return "Invalid list style"


def format_search_results(event_id: int, query: str) -> str:
    """
    Format search results for host.

    Args:
        event_id: Event ID
        query: Search query

    Returns:
        Formatted search results
    """
    results = db.search_guests(event_id, query)

    if not results:
        return f"No results for '{query}'"

    lines = [f"🔍 Results for '{query}':\n"]
    for guest in results:
        name = guest['name'] or mask_phone(guest['phone'])
        status = get_status_emoji(guest['status'])

        # Show invite chain
        if guest['invited_by_phone']:
            inviter = db.get_guest_by_phone(guest['invited_by_phone'], guest['event_id'])
            inviter_name = inviter['name'] if inviter and inviter['name'] else mask_phone(guest['invited_by_phone'])
            quota_status = f"{guest['quota_used']}/2"
            lines.append(f"{status} {name} (invited by {inviter_name}) · invites {quota_status}")
        else:
            quota_status = f"{guest['quota_used']}/2"
            lines.append(f"{status} {name} (initial invite) · invites {quota_status}")

    return '\n'.join(lines)


def handle_host_message(host_phone: str, text: str, event_id: int, vcard_data: dict = None) -> str:
    """
    Handle message from host.

    Args:
        host_phone: Host phone number
        text: Message text
        event_id: Event ID
        vcard_data: Optional parsed vCard data with 'phone' and 'name' keys

    Returns:
        Response text
    """
    # Check if host is answering a forwarded guest question
    host_state = db.get_conversation_state(event_id, host_phone)
    if host_state and host_state['state'] == 'answering_guest_question':
        return _handle_guest_question_reply(host_phone, text, event_id, host_state)

    # Check if host is in event creation flow
    creation_state = get_host_event_creation_state(host_phone)
    if creation_state and creation_state['state'] != 'idle':
        return handle_event_creation_message(host_phone, text)

    # If host sent a contact card, treat as invite
    if vcard_data and vcard_data.get('phone'):
        return handle_send_invites(event_id, [vcard_data['phone']])

    # Check if this is location drop details (contains pipe separator)
    if '|' in text:
        location_details = parse_location_details(text)
        if location_details:
            return handle_location_drop_execution(event_id, location_details)

    # Detect command
    command = detect_host_command(text)

    if command:
        cmd_type, arg = command

        if cmd_type == 'list':
            return format_guest_list(event_id, style='tree')

        elif cmd_type == 'stats':
            return format_guest_list(event_id, style='stats')

        elif cmd_type == 'search' and arg:
            return format_search_results(event_id, arg.strip())

        elif cmd_type == 'drop':
            return handle_location_drop_request(event_id)

        elif cmd_type == 'graph':
            from instagram_social import get_social_graph_summary
            return get_social_graph_summary(event_id)

        elif cmd_type == 'create':
            return start_event_creation(host_phone)

    # Try to detect phone numbers (for sending invites)
    phones = []
    for line in text.split('\n'):
        phone = extract_phone_from_text(line)
        if phone:
            phones.append(phone)

    if phones:
        return handle_send_invites(event_id, phones)

    # No command matched — try LLM for a natural response
    try:
        from llm_responder import answer_host_message
        event = db.get_event(event_id)
        llm_response = answer_host_message(text, event)
        if llm_response:
            return llm_response
    except Exception:
        pass

    return "I didn't catch that. Try 'list', 'stats', 'search [name]', 'graph', or 'drop location'."


def handle_send_invites(event_id: int, phones: List[str]) -> str:
    """
    Handle host sending invites.

    Args:
        event_id: Event ID
        phones: List of phone numbers to invite

    Returns:
        Response text
    """
    sent_count = 0
    already_invited = 0
    errors = []

    for phone in phones:
        try:
            # Check if already invited
            existing = db.get_guest_by_phone(phone, event_id)
            if existing:
                if existing['status'] == 'expired':
                    # Allow re-invite of expired guests
                    import time as _time
                    db.update_guest(existing['id'], status='pending',
                                    invited_by_phone=None, invited_at=int(_time.time()))
                    send_invite(event_id, phone)
                    sent_count += 1
                else:
                    already_invited += 1
                continue

            send_invite(event_id, phone)
            sent_count += 1

        except Exception as e:
            errors.append(f"{phone}: {str(e)}")

    # Build response
    parts = []
    if sent_count > 0:
        parts.append(f"Sent {sent_count} invites.")
    if already_invited > 0:
        parts.append(f"{already_invited} already invited.")
    if errors:
        parts.append(f"Errors: {', '.join(errors)}")

    return '\n'.join(parts) if parts else "No invites sent."


def handle_location_drop_request(event_id: int) -> str:
    """
    Handle host requesting location drop.

    Args:
        event_id: Event ID

    Returns:
        Response text with instructions
    """
    stats = db.get_event_stats(event_id)
    confirmed_count = stats.get('confirmed', 0)

    if confirmed_count == 0:
        return "No confirmed guests yet. Location drop is for confirmed guests only."

    return (
        f"Ready to drop location to {confirmed_count} confirmed guests.\n\n"
        f"Before I send it:\n"
        f"1. What's the address?\n"
        f"2. Any arrival window?\n"
        f"3. Any last notes?\n\n"
        f"Reply with: [address] | [arrival window] | [notes]"
    )


def handle_location_drop_execution(event_id: int, location_details: dict, send_func=None) -> str:
    """
    Execute the location drop with provided details.

    Args:
        event_id: Event ID
        location_details: Dict with address, arrival_window, notes
        send_func: Optional send function (for testing)

    Returns:
        Response text confirming drop initiated
    """
    # Get preview
    preview = get_location_drop_preview(
        event_id,
        location_details['address'],
        location_details.get('arrival_window'),
        location_details.get('notes')
    )

    if preview['recipients'] == 0:
        return "No confirmed guests to send location to."

    # Trigger the drop
    result = trigger_location_drop(
        event_id,
        location_details['address'],
        location_details.get('arrival_window'),
        location_details.get('notes'),
        send_func=send_func
    )

    if result['status'] == 'success':
        return (
            f"Location drop initiated! 🎉\n\n"
            f"Sending to {result['recipients']} confirmed guests:\n"
            f"• Part 1: \"Location drops in 5 minutes\" (sent now)\n"
            f"• Part 2: Address reveal (in 5 minutes)\n\n"
            f"Address: {location_details['address']}"
        )
    else:
        return f"Error: {result['message']}"


def _handle_guest_question_reply(host_phone: str, text: str, event_id: int, host_state: dict) -> str:
    """Handle host replying to a forwarded guest question."""
    context = host_state.get('context', {})
    guest_phone = context.get('guest_phone')
    guest_name = context.get('guest_name', 'Guest')
    question = context.get('question', '')

    if not guest_phone:
        db.upsert_conversation_state(event_id, host_phone, 'idle', {})
        return "Something went wrong — couldn't find the guest. State cleared."

    # Clear the host's answering state
    db.upsert_conversation_state(event_id, host_phone, 'idle', {})

    # Feed host answer through LLM for doorman voice
    try:
        from llm_responder import rewrite_host_answer
        event = db.get_event(event_id)
        guest = db.get_guest_by_phone(guest_phone, event_id)
        polished = rewrite_host_answer(text, question, event, guest)
    except Exception:
        polished = text

    # Send the polished answer to the guest
    if not os.environ.get('FLOWERS_TESTING'):
        try:
            from imsg_integration import send_imessage
            send_imessage(guest_phone, polished)
        except Exception:
            return f"Couldn't send to {guest_name}. Try again."

    return f"Sent to {guest_name}."


def handle_unknown_host_command(text: str) -> str:
    """Handle unrecognized host command."""
    return "I didn't catch that. Try 'list', 'stats', 'search [name]', 'graph', or 'drop location'."
