"""
Conversational event creation for hosts via iMessage.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dateutil import parser as dateutil_parser
from db import db
from phone_utils import normalize_phone


# Relative day keywords
RELATIVE_DAYS = {
    'today': 0, 'tonight': 0,
    'tomorrow': 1, 'tmrw': 1, 'tmr': 1,
}

WEEKDAYS = {
    'monday': 0, 'mon': 0,
    'tuesday': 1, 'tue': 1, 'tues': 1,
    'wednesday': 2, 'wed': 2,
    'thursday': 3, 'thu': 3, 'thurs': 3, 'thur': 3,
    'friday': 4, 'fri': 4,
    'saturday': 5, 'sat': 5,
    'sunday': 6, 'sun': 6,
}


def parse_date(text: str) -> Optional[str]:
    """
    Parse date from virtually any format to YYYY-MM-DD.

    Handles: "Feb 14", "2/14", "next friday", "tomorrow", "March 15 2026",
    "03/15/2026", "2026-03-15", "the 20th", "feb 14th", etc.
    """
    text = text.strip()
    text_lower = text.lower().strip()
    today = datetime.now()

    # Relative days: "today", "tomorrow", "tmrw"
    for keyword, offset in RELATIVE_DAYS.items():
        if text_lower == keyword:
            return (today + timedelta(days=offset)).strftime('%Y-%m-%d')

    # "next <weekday>" or just "<weekday>"
    next_match = re.match(r'(?:next\s+)?(\w+)', text_lower)
    if next_match:
        day_word = next_match.group(1)
        if day_word in WEEKDAYS:
            target = WEEKDAYS[day_word]
            current = today.weekday()
            days_ahead = (target - current) % 7
            if days_ahead == 0:
                days_ahead = 7  # always next occurrence
            return (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

    # "the 20th", "the 3rd" — day of current/next month
    ordinal_match = re.match(r'(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)', text_lower)
    if ordinal_match and len(text_lower) < 10:
        day = int(ordinal_match.group(1))
        if 1 <= day <= 31:
            try:
                candidate = today.replace(day=day)
                if candidate.date() < today.date():
                    # Roll to next month
                    if today.month == 12:
                        candidate = candidate.replace(year=today.year + 1, month=1)
                    else:
                        candidate = candidate.replace(month=today.month + 1)
                return candidate.strftime('%Y-%m-%d')
            except ValueError:
                pass

    # Use dateutil for everything else (handles most formats)
    try:
        parsed = dateutil_parser.parse(text, fuzzy=True, dayfirst=False)
        # If no year was provided, dateutil defaults to current year;
        # if that date is in the past, bump to next year
        if str(parsed.year) not in text and parsed.date() < today.date():
            parsed = parsed.replace(year=parsed.year + 1)
        return parsed.strftime('%Y-%m-%d')
    except (ValueError, OverflowError):
        pass

    return None


def get_host_event_creation_state(host_phone: str) -> Optional[Dict[str, Any]]:
    """
    Get host's event creation state.

    Uses conversation_state table with event_id = 0 for creation in progress.
    """
    state = db.get_conversation_state(0, host_phone)
    return state


def set_host_event_creation_state(host_phone: str, state: str, context: Dict[str, Any]):
    """Set host's event creation state."""
    db.upsert_conversation_state(0, host_phone, state, context)


def clear_host_event_creation_state(host_phone: str):
    """Clear host's event creation state."""
    # Delete the state by setting it to idle
    db.upsert_conversation_state(0, host_phone, 'idle', {})


def start_event_creation(host_phone: str) -> str:
    """
    Start the event creation flow.

    Returns:
        Initial prompt message
    """
    # Initialize creation state
    set_host_event_creation_state(
        host_phone,
        'creating_event_name',
        {'created_at': datetime.now().isoformat()}
    )

    return "Let's create a new event! 🎉\n\nWhat's the event name?"


def handle_event_creation_message(host_phone: str, text: str) -> str:
    """
    Handle a message during event creation flow.

    Args:
        host_phone: Host phone number
        text: Message text

    Returns:
        Response message
    """
    state_record = get_host_event_creation_state(host_phone)

    if not state_record:
        return "No event creation in progress. Text 'create event' to start."

    state = state_record['state']
    context = state_record.get('context', {})

    # Handle cancellation
    if text.lower() in ['cancel', 'stop', 'quit', 'nevermind']:
        clear_host_event_creation_state(host_phone)
        return "Event creation cancelled."

    # Route based on state
    if state == 'creating_event_name':
        return handle_name_input(host_phone, text, context)
    elif state == 'creating_event_date':
        return handle_date_input(host_phone, text, context)
    elif state == 'creating_event_time':
        return handle_time_input(host_phone, text, context)
    elif state == 'creating_event_drop_time':
        return handle_drop_time_input(host_phone, text, context)
    elif state == 'creating_event_rules':
        return handle_rules_input(host_phone, text, context)
    else:
        return "Something went wrong. Text 'create event' to start over."


def handle_name_input(host_phone: str, text: str, context: Dict) -> str:
    """Handle event name input."""
    name = text.strip()

    if len(name) < 3:
        return "Event name too short. What's the event name?"

    if len(name) > 50:
        return f"That name is {len(name)} characters — max is 50. Try a shorter name."

    context['name'] = name
    set_host_event_creation_state(host_phone, 'creating_event_date', context)

    return f"Great! \"{name}\"\n\nWhat's the date? (e.g., Feb 14, 2/14, next friday, tomorrow)"


def handle_date_input(host_phone: str, text: str, context: Dict) -> str:
    """Handle event date input."""
    date = parse_date(text)

    if not date:
        return "I couldn't figure out that date. Try something like:\n• Feb 14\n• 2/14\n• next friday\n• tomorrow"

    # Check if date is in the future
    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        if date_obj.date() < datetime.now().date():
            return "That date is in the past. What's the correct date?"
    except:
        pass

    context['date'] = date
    set_host_event_creation_state(host_phone, 'creating_event_time', context)

    # Format date nicely for confirmation
    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        formatted = date_obj.strftime('%A, %B %d, %Y')
        return f"Perfect! {formatted}\n\nWhat time? (e.g., 7-9 PM)"
    except:
        return f"Date set to {date}.\n\nWhat time? (e.g., 7-9 PM)"


def handle_time_input(host_phone: str, text: str, context: Dict) -> str:
    """Handle event time window input."""
    time_window = text.strip()

    if len(time_window) < 3:
        return "Time too short. What's the time window? (e.g., 7-9 PM)"

    context['time_window'] = time_window
    set_host_event_creation_state(host_phone, 'creating_event_drop_time', context)

    return f"Time: {time_window}\n\nWhen should I drop the location? (e.g., 6:30 PM or '1 hour before')"


def handle_drop_time_input(host_phone: str, text: str, context: Dict) -> str:
    """Handle location drop time input."""
    drop_time = text.strip()

    if len(drop_time) < 2:
        return "Drop time too short. When should I drop the location?"

    context['drop_time'] = drop_time
    set_host_event_creation_state(host_phone, 'creating_event_rules', context)

    return (
        f"Location drops at {drop_time}.\n\n"
        f"Any house rules? (send one per message, or 'none' or 'done')"
    )


def handle_rules_input(host_phone: str, text: str, context: Dict) -> str:
    """Handle house rules input."""
    text_lower = text.strip().lower()

    # Initialize rules list if not exists
    if 'rules' not in context:
        context['rules'] = []

    # Check if done
    if text_lower in ['none', 'done', 'finish', 'no', 'skip']:
        # Create the event
        return create_event_from_context(host_phone, context)

    # Add rule
    rule = text.strip()
    if len(rule) > 3:
        context['rules'].append(rule)
        set_host_event_creation_state(host_phone, 'creating_event_rules', context)
        return f"Rule added: \"{rule}\"\n\nAnother rule? (or 'done')"
    else:
        return "Rule too short. Add a rule, or say 'done'."


def create_event_from_context(host_phone: str, context: Dict) -> str:
    """Create the event from collected context."""
    try:
        # Normalize host phone
        host_phone_normalized = normalize_phone(host_phone)

        # Create event
        event_id = db.create_event(
            name=context['name'],
            event_date=context['date'],
            time_window=context['time_window'],
            location_drop_time=context['drop_time'],
            rules=context.get('rules', []),
            host_phone=host_phone_normalized
        )

        # Clear creation state
        clear_host_event_creation_state(host_phone)

        # Format confirmation
        date_obj = datetime.strptime(context['date'], '%Y-%m-%d')
        formatted_date = date_obj.strftime('%A, %B %d')

        rules_text = ""
        if context.get('rules'):
            rules_list = '\n'.join(f"  • {rule}" for rule in context['rules'])
            rules_text = f"\nRules:\n{rules_list}"

        return (
            f"✅ Event created!\n\n"
            f"📋 {context['name']}\n"
            f"📅 {formatted_date}, {context['time_window']}\n"
            f"📍 Location drops at {context['drop_time']}"
            f"{rules_text}\n\n"
            f"Ready to send invites?\n"
            f"Send phone numbers (one per message) or 'stats' to check status."
        )

    except Exception as e:
        clear_host_event_creation_state(host_phone)
        return f"Error creating event: {str(e)}\n\nText 'create event' to try again."
