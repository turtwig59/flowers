"""
Message routing logic for the Flowers bot.
Routes incoming messages to appropriate handlers based on sender and state.
"""

import json
import os
import re
from typing import Optional, Dict, Any
from db import db
from phone_utils import normalize_phone, extract_phone_from_text


# Pattern matching for responses
YES_PATTERNS = re.compile(r'\b(yes|yeah|yep|yup|sure|absolutely|definitely|ok|okay|k|bet|down|in|count me in|im in|i\'?m in|for sure|of course|let\'?s go|letsgo|say less|less|fs|i\'?m down|im down)\b', re.IGNORECASE)
NO_PATTERNS = re.compile(r'\b(no|nope|nah|can\'?t|cannot|pass|i\'?m good|im good|not this time|maybe next|decline)\b', re.IGNORECASE)

# FAQ patterns
FAQ_PATTERNS = {
    'where': re.compile(r'\b(where|location|place|address)\b', re.IGNORECASE),
    'when': re.compile(r'\b(when|what time|time|date)\b', re.IGNORECASE),
    'plus_one': re.compile(r'\b(bring|plus one|\+1|guest|someone|friend)\b', re.IGNORECASE),
    'drop': re.compile(r'\b(drop|reveal|send|get|receive)\b', re.IGNORECASE),
}

# Host command patterns
HOST_COMMANDS = {
    'create': re.compile(r'\bcreate\s+event\b', re.IGNORECASE),
    'list': re.compile(r'\b(list|guest list|show.*guests?)\b', re.IGNORECASE),
    'search': re.compile(r'\bsearch\s+(.+)', re.IGNORECASE),
    'stats': re.compile(r'\bstats?\b', re.IGNORECASE),
    'drop': re.compile(r'\bdrop\s+location\b', re.IGNORECASE),
    'graph': re.compile(r'\b(graph|connections|social|ig graph)\b', re.IGNORECASE),
}


def is_host(phone: str, event_id: int) -> bool:
    """
    Check if phone number matches event host.

    Args:
        phone: Phone number (will be normalized)
        event_id: Event ID

    Returns:
        True if phone matches host, False otherwise
    """
    try:
        normalized = normalize_phone(phone)
        event = db.get_event(event_id)
        return event and event['host_phone'] == normalized
    except ValueError:
        return False


def detect_yes(text: str) -> bool:
    """Check if text contains YES response."""
    return bool(YES_PATTERNS.search(text))


def detect_no(text: str) -> bool:
    """Check if text contains NO response."""
    return bool(NO_PATTERNS.search(text))


def detect_faq(text: str) -> Optional[str]:
    """
    Detect FAQ question in text.

    Returns:
        FAQ type ('where', 'when', 'plus_one', 'drop') or None
    """
    for faq_type, pattern in FAQ_PATTERNS.items():
        if pattern.search(text):
            return faq_type
    return None


def detect_host_command(text: str) -> Optional[tuple[str, Optional[str]]]:
    """
    Detect host command in text.

    Returns:
        Tuple of (command_type, argument) or None
    """
    for cmd_type, pattern in HOST_COMMANDS.items():
        match = pattern.search(text)
        if match:
            arg = match.group(1) if match.groups() else None
            return (cmd_type, arg)
    return None


def route_message(from_phone: str, text: str, event_id: Optional[int] = None, vcard_path: Optional[str] = None) -> str:
    """
    Route incoming message to appropriate handler.

    Args:
        from_phone: Sender phone number (any format)
        text: Message text
        event_id: Event ID (if None, uses active event)
        vcard_path: Optional path to a vCard attachment file

    Returns:
        Response text to send back
    """
    # Import handlers here to avoid circular imports
    from guest_handlers import (
        handle_invite_response,
        handle_name_collection,
        handle_instagram_collection,
        handle_plus_one_offer,
        handle_contact_submission,
        handle_faq,
        handle_unknown_state
    )
    from host_commands import (
        handle_host_message,
        handle_unknown_host_command
    )

    # Parse vCard if attachment provided
    vcard_data = None
    if vcard_path:
        try:
            from contact_parser import parse_vcard_file
            vcard_data = parse_vcard_file(vcard_path)
        except Exception:
            pass

    # Normalize phone
    try:
        normalized_phone = normalize_phone(from_phone)
    except ValueError:
        return "Sorry, I couldn't recognize your phone number."

    # Check if someone is trying to create an event or is in creation flow
    from event_creation import get_host_event_creation_state, start_event_creation, handle_event_creation_message
    creation_state = get_host_event_creation_state(normalized_phone)

    # If in event creation flow, handle that
    if creation_state and creation_state['state'] != 'idle':
        return handle_event_creation_message(normalized_phone, text)

    # If starting event creation
    if 'create' in text.lower() and 'event' in text.lower():
        return start_event_creation(normalized_phone)

    # Get active event if not specified
    if event_id is None:
        event = db.get_active_event()
        if not event:
            return "No active event. Text 'create event' to start a new event."
        event_id = event['id']

    # Check if host
    if is_host(normalized_phone, event_id):
        return handle_host_message(normalized_phone, text, event_id, vcard_data=vcard_data)

    # Check if known guest
    guest = db.get_guest_by_phone(normalized_phone, event_id)
    if not guest:
        try:
            from llm_responder import answer_unknown_sender
            llm_response = answer_unknown_sender(text)
            if llm_response:
                return llm_response
        except Exception:
            pass
        return "I don't have you on the list. If you think this is a mistake, reach out to whoever invited you."

    # Block all interaction from expired guests
    if guest['status'] == 'expired':
        return "Sorry, your invite has expired."

    # Get conversation state
    state_record = db.get_conversation_state(event_id, normalized_phone)
    state = state_record['state'] if state_record else 'idle'

    # Check for FAQ across all states (FAQ can be asked anytime)
    faq_type = detect_faq(text)
    if faq_type:
        return handle_faq(guest, faq_type, event_id)

    # Route based on state
    if state == 'waiting_for_response':
        return handle_invite_response(guest, text, event_id)
    elif state == 'waiting_for_name':
        return handle_name_collection(guest, text, event_id)
    elif state == 'waiting_for_instagram':
        return handle_instagram_collection(guest, text, event_id)
    elif state == 'waiting_for_plus_one':
        return handle_plus_one_offer(guest, text, event_id, vcard_data=vcard_data)
    elif state == 'waiting_for_contact':
        return handle_contact_submission(guest, text, event_id, vcard_data=vcard_data)
    elif state == 'idle':
        # Check if trying to send a phone number or contact card (potential +1 invite)
        if vcard_data and vcard_data.get('phone'):
            return handle_contact_submission(guest, text, event_id, vcard_data=vcard_data)
        phone = extract_phone_from_text(text)
        if phone:
            return handle_contact_submission(guest, text, event_id)
        else:
            # Route through LLM for natural Q&A
            try:
                from llm_responder import answer_question
                event = db.get_event(event_id)
                llm_response = answer_question(text, event, guest)
                if llm_response and llm_response.startswith('[ESCALATE]'):
                    # LLM needs host input — forward question to host
                    _escalate_to_host(event, guest, text, event_id)
                    return "Let me check on that for you."
                if llm_response:
                    return llm_response
            except Exception:
                pass
            # Fallback if LLM unavailable
            return "Hey! If you have questions about the event, just ask. I can tell you about location, timing, or +1s."
    else:
        return handle_unknown_state(guest, state, event_id)


def _escalate_to_host(event: Dict, guest: Dict, question: str, event_id: int):
    """Forward a guest question to the host and store pending state."""
    host_phone = event['host_phone']
    guest_name = guest.get('name') or guest['phone']

    # Store pending question in host's conversation state
    db.upsert_conversation_state(
        event_id,
        host_phone,
        'answering_guest_question',
        {
            'guest_phone': guest['phone'],
            'guest_name': guest_name,
            'question': question,
        }
    )

    # Send the question to the host
    msg = f"{guest_name} asked: \"{question}\"\n\nReply and I'll pass it along."
    if not os.environ.get('FLOWERS_TESTING'):
        try:
            from imsg_integration import send_imessage
            send_imessage(host_phone, msg)
        except Exception:
            pass


def get_conversation_context(phone: str, event_id: int) -> Dict[str, Any]:
    """
    Get full conversation context for a guest.

    Args:
        phone: Guest phone number
        event_id: Event ID

    Returns:
        Dict with event, guest, state, and recent messages
    """
    return {
        'event': db.get_event(event_id),
        'guest': db.get_guest_by_phone(phone, event_id),
        'state': db.get_conversation_state(event_id, phone),
        'recent_messages': db.get_recent_messages(phone, event_id, limit=10)
    }
