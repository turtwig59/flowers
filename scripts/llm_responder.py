"""
LLM-powered Q&A for guest questions about the event.
Uses Claude Haiku for fast, low-cost responses.
Helpful but guarded — shares logistics, protects secrets.
"""

import json
import os
from typing import Dict, Any, Optional

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SYSTEM_PROMPT = """You are Yed, a text-only doorman for an exclusive event. You speak in short, confident texts — NYC energy, no fluff. You're helpful but guarded.

RULES:
- You CAN share: event name, date, time window, dress code vibes, general energy
- You CANNOT share: exact location (it drops later), who else is coming, guest count, the host's identity, or any surprise elements
- If asked about location: "Location drops day-of. That's how this works."
- If asked who's coming: "You'll see when you get there."
- If asked who's hosting: "Someone with taste."
- Keep responses to 1-3 sentences max. Text message style — not formal.
- Never break character. You're the doorman, not a chatbot.
- If the question has nothing to do with the event, keep it brief and steer back: "I'm just the doorman. Got questions about the event?"

IMPORTANT: If you genuinely don't have enough information to answer the question (something specific the host would need to weigh in on — like special accommodations, parking, dietary needs, whether something specific is allowed), respond with EXACTLY this format:
[ESCALATE] <one sentence summary of what the guest is asking>

Only escalate for things you truly can't answer from the event details. Most questions you can handle yourself."""

REWRITE_PROMPT = """You are Yed, a text-only doorman. Rewrite the host's answer in your voice — short, confident, NYC energy. Keep the actual information intact but make it sound like it's coming from you, the doorman. 1-2 sentences max."""

HOST_SYSTEM_PROMPT = """You are Yed, a text-only doorman assistant for the event host. You speak in short, confident texts — NYC energy. The host manages the event through you.

RULES:
- Keep responses to 1-2 sentences. Text style.
- If the host seems to be making casual conversation, engage briefly but stay in character.
- If they seem to want to do something event-related, remind them of available commands: list, stats, search [name], graph, drop location, or send phone numbers to invite.
- Never break character."""

UNKNOWN_SENDER_PROMPT = """You are Yed, a text-only doorman for an exclusive event. Someone who is NOT on the guest list just texted you. You speak in short, confident texts — NYC energy.

RULES:
- You don't know this person. They're not on the list.
- Be polite but firm. 1-2 sentences max.
- If they're asking about the event or trying to get in, tell them you don't have them on the list and they should reach out to whoever invited them.
- If they're just chatting or saying something random, keep it brief and let them know they're not on the list.
- Never break character."""


def get_client():
    """Get Anthropic client, or None if unavailable."""
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:
        return None


def _build_event_context(event: Dict[str, Any], guest: Optional[Dict] = None) -> str:
    """Build event context string for LLM prompts."""
    rules = event.get('rules', '[]')
    if isinstance(rules, str):
        try:
            rules = json.loads(rules)
        except:
            rules = []

    rules_text = "\n".join(f"- {r}" for r in rules) if rules else "None specified"

    guest_name = ""
    if guest and guest.get('name'):
        guest_name = f"You're talking to {guest['name']}. "

    return f"""EVENT DETAILS (for your reference — share selectively):
- Event: {event.get('name', 'Unknown')}
- Date: {event.get('event_date', 'TBD')}
- Time: {event.get('time_window', 'TBD')}
- Location drop time: {event.get('location_drop_time', 'Day of')}
- House rules: {rules_text}

{guest_name}They are confirmed on the list."""


def answer_question(text: str, event: Dict[str, Any], guest: Optional[Dict] = None) -> Optional[str]:
    """
    Answer a guest's question using Claude.

    Returns:
        Response string (may start with "[ESCALATE]" if LLM needs host input),
        or None if LLM unavailable.
    """
    client = get_client()
    if not client:
        return None

    event_context = _build_event_context(event, guest)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"{event_context}\n\nGuest asks: {text}"}
            ]
        )
        return response.content[0].text
    except Exception:
        return None


PARSE_PROMPT = """You are a parser for an iMessage bot. Given a conversation context and a user message, extract the intent as JSON. Be generous in interpretation — people text casually.

Respond with ONLY a JSON object, no other text. The JSON schema depends on the context provided."""


def parse_message(text: str, context: str) -> Optional[Dict]:
    """
    Use Claude to parse an ambiguous message based on conversation context.

    Args:
        text: The user's message
        context: What we're expecting (e.g., "yes_or_no", "name", "instagram")

    Returns:
        Parsed dict or None if LLM unavailable.
    """
    client = get_client()
    if not client:
        return None

    prompts = {
        "yes_or_no": (
            'The bot asked a yes/no question (e.g., "want to come?" or "want to invite someone?").\n'
            'Determine: is this a YES, NO, or UNCLEAR?\n'
            'Return: {"intent": "yes"} or {"intent": "no"} or {"intent": "unclear"}\n'
            'Be generous — "bet", "down", "lol sure why not", "i guess", "yea def" are all YES.\n'
            '"im good", "nah maybe next time", "can\'t make it" are all NO.'
        ),
        "name": (
            'The bot asked "What\'s your name?" and the user replied.\n'
            'Extract their name from whatever they said.\n'
            'Return: {"name": "First Last"} or {"name": null} if truly no name is present.\n'
            'Handle: "I\'m Alice", "they call me Bob", "Alice!", "yo its marcus", "haha im jenny", etc.'
        ),
        "instagram": (
            'The bot asked for their Instagram handle.\n'
            'Extract the handle OR determine they want to skip.\n'
            'Return: {"handle": "username"} (without @) or {"skip": true}\n'
            'Handle: "my ig is alice_nyc", "@alice", "don\'t have one", "instagram.com/alice", '
            '"no insta", "its alice.v", "lol i don\'t use that", etc.'
        ),
        "plus_one_or_contact": (
            'The bot asked if they want to invite someone (+1) to an event.\n'
            'Determine: YES (wants to invite), NO (doesn\'t want to), or they\'re already providing a phone number/contact.\n'
            'Return: {"intent": "yes"} or {"intent": "no"} or {"intent": "unclear"}\n'
            'If they included a phone number: {"intent": "contact", "phone": "the number"}\n'
            '"yeah lemme add my boy" = yes. "nah im coming solo" = no. "yeah here +15551234567" = contact.'
        ),
    }

    if context not in prompts:
        return None

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=PARSE_PROMPT,
            messages=[
                {"role": "user", "content": f"{prompts[context]}\n\nUser message: \"{text}\""}
            ]
        )
        result = response.content[0].text.strip()
        # Handle markdown code blocks
        if result.startswith("```"):
            result = result.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(result)
    except Exception:
        return None


def rewrite_host_answer(host_answer: str, original_question: str, event: Dict[str, Any], guest: Optional[Dict] = None) -> Optional[str]:
    """
    Rewrite the host's answer in the doorman's voice.

    Args:
        host_answer: The host's raw reply
        original_question: What the guest originally asked
        event: Event record
        guest: Guest record

    Returns:
        Polished response in doorman voice, or the raw answer if LLM fails.
    """
    client = get_client()
    if not client:
        return host_answer

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=REWRITE_PROMPT,
            messages=[
                {"role": "user", "content": f"Guest asked: \"{original_question}\"\nHost answered: \"{host_answer}\"\n\nRewrite in your voice:"}
            ]
        )
        return response.content[0].text
    except Exception:
        return host_answer


def answer_host_message(text: str, event: Dict[str, Any]) -> Optional[str]:
    """Answer a host message that didn't match any command."""
    client = get_client()
    if not client:
        return None

    event_context = _build_event_context(event)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=HOST_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"{event_context}\n\nHost says: {text}"}
            ]
        )
        return response.content[0].text
    except Exception:
        return None


def answer_unknown_sender(text: str) -> Optional[str]:
    """Respond to a message from someone not on the guest list."""
    client = get_client()
    if not client:
        return None

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=UNKNOWN_SENDER_PROMPT,
            messages=[
                {"role": "user", "content": text}
            ]
        )
        return response.content[0].text
    except Exception:
        return None
