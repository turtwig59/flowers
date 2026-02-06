"""
Guest conversation handlers - state machine for guest interactions.
"""

from typing import Dict, Any, Optional
from db import db
from phone_utils import extract_phone_from_text, normalize_phone, is_valid_phone
from contact_parser import extract_name_from_text
from contacts_util import upsert_contact
from message_router import detect_yes, detect_no
from daily_log import log_guest_response, log_plus_one_used


# Response templates matching the tone guidelines
RESPONSES = {
    'accepted_ask_name': "Great! What's your name?",
    'accepted_ask_name_alt': "Perfect! What should I call you?",

    'name_received_offer_plus_one': "You get two invites to share. Want to invite someone?",
    'name_received_offer_plus_one_alt': "You can bring up to two people. Want to invite someone?",

    'plus_one_accepted': "Send me a contact card or their phone number.",

    'plus_one_declined': "No problem. See you there!\n\nGot questions about the event? Just ask.",

    'invite_sent': "Invite sent! I'll let you know when they respond.\n\nGot questions about the event? Just ask.",

    'declined': "Thanks for letting me know!",

    'quota_exceeded': "You've used both invites! Each guest gets two invites to share.",

    'invalid_name': "Got it — what name should I use for the list? (first name is fine)",

    'invalid_phone': "That doesn't look like a valid number. Can you send a contact card or try again?",

    'already_invited': "This person is already invited!",
}


def handle_invite_response(guest: Dict[str, Any], text: str, event_id: int) -> str:
    """
    Handle guest response to initial invite (YES or NO).

    State transition:
        waiting_for_response → waiting_for_name (if YES)
        waiting_for_response → idle (if NO, status=declined)
    """
    if guest['status'] == 'expired':
        return "Sorry, your invite has expired."

    if detect_yes(text):
        # Accept invite
        db.update_guest(guest['id'], status='confirmed')

        # Update state to waiting for name
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'waiting_for_name',
            {'accepted': True}
        )

        # Log acceptance
        try:
            event = db.get_event(event_id)
            log_guest_response(event['name'], guest.get('name', 'Unknown'), guest['phone'], 'accepted')
        except:
            pass

        return RESPONSES['accepted_ask_name']

    elif detect_no(text):
        # Decline invite
        db.update_guest(guest['id'], status='declined')

        # Update state to idle
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'idle',
            {'declined': True}
        )

        # Log decline
        try:
            event = db.get_event(event_id)
            log_guest_response(event['name'], guest.get('name', 'Unknown'), guest['phone'], 'declined')
        except:
            pass

        return RESPONSES['declined']

    else:
        # Regex didn't match — try LLM
        try:
            from llm_responder import parse_message
            parsed = parse_message(text, "yes_or_no")
            if parsed and parsed.get('intent') == 'yes':
                return handle_invite_response(guest, "yes", event_id)
            elif parsed and parsed.get('intent') == 'no':
                return handle_invite_response(guest, "no", event_id)
        except Exception:
            pass
        # Still unclear
        event = db.get_event(event_id)
        return f"Reply YES to confirm for {event['name']} or NO to pass."


def handle_name_collection(guest: Dict[str, Any], text: str, event_id: int) -> str:
    """
    Handle guest providing their name.

    State transition:
        waiting_for_name → waiting_for_instagram
    """
    # Extract name from text
    name = extract_name_from_text(text)

    # Try regex first, then LLM
    if not name:
        try:
            from llm_responder import parse_message
            parsed = parse_message(text, "name")
            if parsed and parsed.get('name'):
                name = parsed['name']
        except Exception:
            pass

    if name:
        # Update guest with name
        db.update_guest(guest['id'], name=name)

        # Save to macOS Contacts for host auditing
        try:
            upsert_contact(guest['phone'], name)
        except Exception:
            pass

        # Update state to waiting for instagram
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'waiting_for_instagram',
            {'name_provided': name}
        )

        return f"What's your Instagram? (or say \"skip\" if you don't have one)"
    else:
        # Name extraction failed, ask for clarification
        return RESPONSES['invalid_name']


def _extract_instagram_handle(text: str) -> Optional[str]:
    """
    Extract an Instagram handle from natural text.

    Handles: "@alice", "alice_nyc", "my ig is alice", "instagram.com/alice",
    "it's @alice on insta", "ig: alice", etc.
    """
    import re
    text = text.strip()

    # Try instagram.com URL
    url_match = re.search(r'instagram\.com/([a-zA-Z0-9._]{1,30})', text)
    if url_match:
        return url_match.group(1)

    # Try @handle anywhere in text
    at_match = re.search(r'@([a-zA-Z0-9._]{1,30})', text)
    if at_match:
        return at_match.group(1)

    # Strip common prefixes: "my ig is", "it's", "ig:", "insta:", etc.
    cleaned = re.sub(
        r'^(my\s+)?(ig|insta|instagram)\s*(is|:)?\s*',
        '', text, flags=re.IGNORECASE
    ).strip()

    # Also strip "it's", "its"
    cleaned = re.sub(r'^(it\'?s\s+)', '', cleaned, flags=re.IGNORECASE).strip()

    # Check if what's left looks like a handle
    if re.match(r'^[a-zA-Z0-9._]{1,30}$', cleaned):
        return cleaned

    # Last try: the whole text is just a handle
    if re.match(r'^[a-zA-Z0-9._]{1,30}$', text):
        return text

    return None


def _is_instagram_skip(text: str) -> bool:
    """Detect if the user is declining to share their Instagram."""
    import re
    text = text.strip().lower()

    skip_phrases = [
        'skip', 'no', 'nah', 'nope', 'none', 'n/a', 'na', 'pass',
    ]
    if text in skip_phrases:
        return True

    # Natural language skips
    skip_patterns = [
        r"don'?t have",
        r"no (ig|insta|instagram)",
        r"don'?t (use|do|have) (ig|insta|instagram)",
        r"i'?m not on",
        r"not on (ig|insta|instagram)",
        r"no social",
        r"don'?t (use|do|have) (social|that)",
    ]
    for pattern in skip_patterns:
        if re.search(pattern, text):
            return True

    return False


def handle_instagram_collection(guest: Dict[str, Any], text: str, event_id: int) -> str:
    """
    Handle guest providing their Instagram handle.

    State transition:
        waiting_for_instagram → waiting_for_plus_one
    """
    # Check if skipping
    if _is_instagram_skip(text):
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'waiting_for_plus_one',
            {'instagram_skipped': True}
        )
        return RESPONSES['name_received_offer_plus_one']

    # Try regex first, then LLM
    handle = _extract_instagram_handle(text)

    if not handle:
        try:
            from llm_responder import parse_message
            parsed = parse_message(text, "instagram")
            if parsed:
                if parsed.get('skip'):
                    return handle_instagram_collection(guest, "skip", event_id)
                if parsed.get('handle'):
                    handle = parsed['handle'].lstrip('@')
        except Exception:
            pass

    if handle:
        db.update_guest(guest['id'], instagram=f"@{handle}")

        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'waiting_for_plus_one',
            {'instagram': f"@{handle}"}
        )

        # Trigger background IG follow + scrape
        try:
            from instagram_social import trigger_ig_follow_and_scrape
            trigger_ig_follow_and_scrape(event_id, guest['id'], handle)
        except Exception:
            pass

        return RESPONSES['name_received_offer_plus_one']
    else:
        return "Couldn't find a handle in that. Drop your @ or say \"skip\"."


def handle_plus_one_offer(guest: Dict[str, Any], text: str, event_id: int, vcard_data: Optional[Dict] = None) -> str:
    """
    Handle guest response to +1 offer.

    State transition:
        waiting_for_plus_one → waiting_for_contact (if YES)
        waiting_for_plus_one → idle (if NO)
    """
    if guest['quota_used'] >= 2:
        db.upsert_conversation_state(event_id, guest['phone'], 'idle', {'plus_one_expired': True})
        return "Your invite window has closed. See you at the event!"

    # If they sent a vCard, treat as implicit "yes + here's the contact"
    if vcard_data and vcard_data.get('phone'):
        return handle_contact_submission(guest, text, event_id, vcard_data=vcard_data)

    if detect_yes(text):
        # Guest wants to invite someone
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'waiting_for_contact',
            {'wants_plus_one': True}
        )

        return RESPONSES['plus_one_accepted']

    elif detect_no(text):
        # Guest doesn't want to invite anyone
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'idle',
            {'declined_plus_one': True}
        )

        return RESPONSES['plus_one_declined']

    else:
        # Check if they sent a phone number or contact info directly
        phone = extract_phone_from_text(text)
        if phone:
            return handle_contact_submission(guest, text, event_id)

        # Regex didn't match — try LLM
        try:
            from llm_responder import parse_message
            parsed = parse_message(text, "plus_one_or_contact")
            if parsed:
                if parsed.get('intent') == 'yes':
                    return handle_plus_one_offer(guest, "yes", event_id)
                elif parsed.get('intent') == 'no':
                    return handle_plus_one_offer(guest, "no", event_id)
                elif parsed.get('intent') == 'contact' and parsed.get('phone'):
                    return handle_contact_submission(guest, parsed['phone'], event_id)
        except Exception:
            pass

        return "Want to invite someone? Send me their contact card or phone number, or reply NO if not."


def handle_contact_submission(guest: Dict[str, Any], text: str, event_id: int, vcard_data: Optional[Dict] = None) -> str:
    """
    Handle guest submitting a contact (phone number, contact card, or vCard).

    State transition:
        waiting_for_contact → idle (after processing)
    """
    # Check quota
    can_invite, reason = db.can_invite_plus_one(guest['id'])
    if not can_invite:
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'idle',
            {'quota_check_failed': reason}
        )
        return RESPONSES['quota_exceeded']

    # Extract phone number — from vCard if available, otherwise from text
    if vcard_data and vcard_data.get('phone'):
        phone = vcard_data['phone']
    else:
        phone = extract_phone_from_text(text)

    if not phone:
        # Couldn't extract phone
        state = db.get_conversation_state(event_id, guest['phone'])
        retry_count = state.get('context', {}).get('retry_count', 0) if state else 0

        # Update retry count
        db.upsert_conversation_state(
            event_id,
            guest['phone'],
            'waiting_for_contact',
            {'retry_count': retry_count + 1}
        )

        return RESPONSES['invalid_phone']

    # Normalize phone
    try:
        normalized_phone = normalize_phone(phone)
    except ValueError:
        return RESPONSES['invalid_phone']

    # Check if already invited
    existing = db.get_guest_by_phone(normalized_phone, event_id)
    if existing:
        if existing['status'] == 'expired':
            # Allow re-invite of expired guests — reset their record and re-send
            return _reinvite_expired_guest(guest, existing, event_id, normalized_phone)
        return RESPONSES['already_invited']

    # Use quota and create new guest
    try:
        new_guest_id = db.use_quota(guest['id'], normalized_phone)

        # Send invite to new guest
        from invite_sender import send_invite
        send_invite(event_id, normalized_phone, invited_by_phone=guest['phone'])

        # Log +1 usage
        try:
            event = db.get_event(event_id)
            log_plus_one_used(event['name'], guest.get('name', 'Unknown'), None, normalized_phone)
        except:
            pass

        # Check if guest has invites remaining
        updated_guest = db.get_guest(guest['id'])
        if updated_guest['quota_used'] < 2:
            db.upsert_conversation_state(
                event_id,
                guest['phone'],
                'idle',
                {'invited_plus_one': normalized_phone}
            )
            return RESPONSES['invite_sent'] + "\n\nYou have one more invite. Want to invite someone else?"
        else:
            db.upsert_conversation_state(
                event_id,
                guest['phone'],
                'idle',
                {'invited_plus_one': normalized_phone}
            )
            return RESPONSES['invite_sent']

    except ValueError as e:
        # Quota error or other issue
        return str(e)


def _reinvite_expired_guest(inviter: Dict[str, Any], expired_guest: Dict[str, Any], event_id: int, phone: str) -> str:
    """Re-invite a guest whose previous invite expired."""
    # Check quota
    can_invite, reason = db.can_invite_plus_one(inviter['id'])
    if not can_invite:
        db.upsert_conversation_state(event_id, inviter['phone'], 'idle', {'quota_check_failed': reason})
        return RESPONSES['quota_exceeded']

    # Reset expired guest record with fresh invite timestamp
    import time as _time
    db.update_guest(expired_guest['id'], status='pending',
                    invited_by_phone=inviter['phone'], invited_at=int(_time.time()))

    # Use inviter's quota
    db.update_guest(inviter['id'], quota_used=inviter['quota_used'] + 1)

    # Re-send invite
    from invite_sender import send_invite
    send_invite(event_id, phone, invited_by_phone=inviter['phone'])

    # Log
    try:
        event = db.get_event(event_id)
        log_plus_one_used(event['name'], inviter.get('name', 'Unknown'), None, phone)
    except:
        pass

    # Check remaining invites
    updated_inviter = db.get_guest(inviter['id'])
    db.upsert_conversation_state(event_id, inviter['phone'], 'idle', {'invited_plus_one': phone})
    if updated_inviter['quota_used'] < 2:
        return RESPONSES['invite_sent'] + "\n\nYou have one more invite. Want to invite someone else?"
    return RESPONSES['invite_sent']


def handle_faq(guest: Dict[str, Any], faq_type: str, event_id: int) -> str:
    """
    Handle FAQ questions from guests.

    Args:
        guest: Guest record
        faq_type: Type of FAQ ('where', 'when', 'plus_one', 'drop')
        event_id: Event ID

    Returns:
        Response text
    """
    event = db.get_event(event_id)

    if faq_type == 'where':
        return f"Location drops at {event['location_drop_time']} on the day of."

    elif faq_type == 'when':
        return f"{event['event_date']}, {event['time_window']}. Location drops at {event['location_drop_time']}."

    elif faq_type == 'plus_one':
        if guest['status'] == 'confirmed':
            if guest['quota_used'] == 0:
                return "You get two invites to share! Want to invite someone now?"
            elif guest['quota_used'] == 1:
                return "You have one invite left! Want to use it?"
            else:
                return "You've used both your invites."
        else:
            return "You get two invites to share after you confirm."

    elif faq_type == 'drop':
        return f"Location drops at {event['location_drop_time']} on {event['event_date']}."

    else:
        return "If you have questions, just ask! I can tell you about location, timing, or bringing someone."


def handle_unknown_state(guest: Dict[str, Any], state: str, event_id: int) -> str:
    """Handle unexpected state - reset to idle."""
    db.upsert_conversation_state(
        event_id,
        guest['phone'],
        'idle',
        {'error': f'Unknown state: {state}'}
    )
    return "Something went wrong. Let's start over - do you have questions about the event?"
