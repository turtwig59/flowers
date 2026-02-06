#!/usr/bin/env python3
"""
iMessage integration for Flowers bot.
This script bridges iMessage (via imsg CLI) with the bot logic.
"""

import sys
import subprocess
from message_router import route_message
from db import db
from phone_utils import normalize_phone


def send_imessage(to_phone: str, text: str):
    """
    Send an iMessage using the imsg CLI.

    Args:
        to_phone: Recipient phone number
        text: Message text
    """
    try:
        # Use imsg CLI to send message (correct syntax with --to and --text flags)
        result = subprocess.run(
            ['imsg', 'send', '--to', to_phone, '--text', text],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"Error sending message: {result.stderr}", file=sys.stderr)
            return False

        print(f"✅ Sent to {to_phone}")
        return True
    except FileNotFoundError:
        print("Error: 'imsg' command not found. Install with: brew install imsg", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error sending message: {e}", file=sys.stderr)
        return False


def handle_incoming_message(from_phone: str, text: str, event_id: int = None, vcard_path: str = None) -> bool:
    """
    Handle incoming iMessage and send response.

    Args:
        from_phone: Sender phone number
        text: Message text
        event_id: Optional event ID (uses active event if not specified)
        vcard_path: Optional path to a vCard attachment file

    Returns:
        True if handled successfully
    """
    try:
        # Get active event if not specified
        if event_id is None:
            active = db.get_active_event()
            if not active:
                send_imessage(from_phone, "No active event right now.")
                return False
            event_id = active['id']

        # Route message and get response
        response = route_message(from_phone, text, event_id, vcard_path=vcard_path)

        # Log the messages
        try:
            normalized_phone = normalize_phone(from_phone)
            event = db.get_event(event_id)

            # Log incoming message
            db.log_message(
                from_phone=normalized_phone,
                to_phone=event['host_phone'],
                message_text=text,
                direction='inbound',
                event_id=event_id
            )

            # Log outgoing message
            db.log_message(
                from_phone=event['host_phone'],
                to_phone=normalized_phone,
                message_text=response,
                direction='outbound',
                event_id=event_id
            )
        except:
            pass  # Don't let logging errors break message handling

        # Send response
        return send_imessage(from_phone, response)

    except Exception as e:
        print(f"Error handling message: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

        # Try to send error message to user
        try:
            send_imessage(from_phone, "Sorry, something went wrong. Please try again.")
        except:
            pass

        return False


def main():
    """
    Main entry point for message handling.

    Usage:
        python3 imsg_integration.py <from_phone> <message_text> [--vcard <path>]
    """
    if len(sys.argv) < 3:
        print("Usage: python3 imsg_integration.py <from_phone> <message_text> [--vcard <path>]")
        sys.exit(1)

    # Parse --vcard flag
    vcard_path = None
    args = sys.argv[1:]
    if '--vcard' in args:
        vcard_idx = args.index('--vcard')
        if vcard_idx + 1 < len(args):
            vcard_path = args[vcard_idx + 1]
            args = args[:vcard_idx] + args[vcard_idx + 2:]

    from_phone = args[0]
    text = ' '.join(args[1:])

    success = handle_incoming_message(from_phone, text, vcard_path=vcard_path)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
