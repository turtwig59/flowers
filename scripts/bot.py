#!/usr/bin/env python3
"""
Flowers - iMessage Party Invite Bot

Main CLI for managing events and processing messages.
"""

import sys
import argparse
import json
from datetime import datetime
from typing import Optional

from db import db
from phone_utils import normalize_phone, extract_phone_from_text
from message_router import route_message
from invite_sender import send_invite, format_date
from host_commands import format_guest_list
from location_drop import trigger_location_drop, parse_location_details


def init_command(args):
    """Initialize the database."""
    from init_db import init_database
    init_database()
    print("✅ Database initialized successfully")


def create_event_command(args):
    """Create a new event."""
    # Interactive mode if no args provided
    if not args.name:
        print("📋 Create New Event\n")
        name = input("Event name: ")
        event_date = input("Date (YYYY-MM-DD): ")
        time_window = input("Time window (e.g., 7-9 PM): ")
        location_drop_time = input("Location drop time (e.g., 6:30 PM): ")

        rules = []
        print("\nHouse rules (press Enter when done):")
        while True:
            rule = input(f"  Rule {len(rules) + 1}: ")
            if not rule:
                break
            rules.append(rule)

        host_phone = input("\nHost phone number: ")
    else:
        name = args.name
        event_date = args.date
        time_window = args.time_window
        location_drop_time = args.drop_time
        rules = args.rules if args.rules else []
        host_phone = args.host_phone

    # Normalize host phone
    try:
        host_phone = normalize_phone(host_phone)
    except ValueError as e:
        print(f"❌ Error: {e}")
        return

    # Create event
    event_id = db.create_event(
        name=name,
        event_date=event_date,
        time_window=time_window,
        location_drop_time=location_drop_time,
        rules=rules,
        host_phone=host_phone
    )

    print(f"\n✅ Event created! ID: {event_id}")
    print(f"📅 {name}")
    print(f"📆 {format_date(event_date)}, {time_window}")
    print(f"📍 Location drops at {location_drop_time}")
    print(f"👤 Host: {host_phone}")


def send_invites_command(args):
    """Send initial invites."""
    event_id = args.event_id or db.get_active_event()['id']

    if not event_id:
        print("❌ No active event found")
        return

    event = db.get_event(event_id)
    print(f"📤 Sending invites for: {event['name']}\n")

    # Get phone numbers
    if args.phones:
        phones = args.phones
    else:
        print("Enter phone numbers (one per line, press Enter twice when done):")
        phones = []
        while True:
            phone = input().strip()
            if not phone:
                break
            phones.append(phone)

    # Normalize and send
    sent_count = 0
    errors = []

    for phone_raw in phones:
        try:
            phone = normalize_phone(phone_raw)

            # Check if already invited
            existing = db.get_guest_by_phone(phone, event_id)
            if existing:
                print(f"⏭️  {phone} - already invited")
                continue

            # Send invite
            send_invite(event_id, phone)
            print(f"✅ {phone} - sent")
            sent_count += 1

        except Exception as e:
            errors.append(f"{phone_raw}: {str(e)}")
            print(f"❌ {phone_raw} - error: {e}")

    print(f"\n📊 Summary: {sent_count} sent")
    if errors:
        print(f"❌ Errors: {len(errors)}")


def handle_message_command(args):
    """Handle an incoming message."""
    from_phone = args.from_phone
    text = args.text
    event_id = args.event_id

    # Get active event if not specified
    if not event_id:
        active = db.get_active_event()
        if not active:
            print("❌ No active event")
            return
        event_id = active['id']

    # Route message
    try:
        response = route_message(from_phone, text, event_id)
        print(f"\n📱 Response:\n{response}")

        # Log to database
        try:
            normalized_phone = normalize_phone(from_phone)
            event = db.get_event(event_id)
            db.log_message(
                from_phone=normalized_phone,
                to_phone=event['host_phone'],
                message_text=text,
                direction='inbound',
                event_id=event_id
            )
            db.log_message(
                from_phone=event['host_phone'],
                to_phone=normalized_phone,
                message_text=response,
                direction='outbound',
                event_id=event_id
            )
        except:
            pass  # Logging errors shouldn't break message handling

        return response

    except Exception as e:
        print(f"❌ Error handling message: {e}")
        import traceback
        traceback.print_exc()


def stats_command(args):
    """Show event statistics."""
    event_id = args.event_id

    if not event_id:
        active = db.get_active_event()
        if not active:
            print("❌ No active event")
            return
        event_id = active['id']

    response = format_guest_list(event_id, style='stats')
    print(response)


def list_command(args):
    """Show guest list."""
    event_id = args.event_id

    if not event_id:
        active = db.get_active_event()
        if not active:
            print("❌ No active event")
            return
        event_id = active['id']

    style = args.style or 'tree'
    response = format_guest_list(event_id, style=style)
    print(response)


def drop_location_command(args):
    """Trigger location drop."""
    event_id = args.event_id

    if not event_id:
        active = db.get_active_event()
        if not active:
            print("❌ No active event")
            return
        event_id = active['id']

    # Get location details
    if not args.address:
        print("📍 Location Drop\n")
        address = input("Address: ")
        arrival_window = input("Arrival window (optional): ")
        notes = input("Notes (optional): ")
    else:
        address = args.address
        arrival_window = args.arrival_window
        notes = args.notes

    # Trigger drop
    result = trigger_location_drop(
        event_id,
        address,
        arrival_window,
        notes
    )

    if result['status'] == 'success':
        print(f"\n✅ Location drop initiated!")
        print(f"📤 Sending to {result['recipients']} confirmed guests")
        print(f"⏰ Part 1: Warning message (sent now)")
        print(f"⏰ Part 2: Address reveal (in 5 minutes)")
    else:
        print(f"❌ Error: {result['message']}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Flowers - iMessage Party Invite Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # init
    parser_init = subparsers.add_parser('init', help='Initialize database')
    parser_init.set_defaults(func=init_command)

    # create-event
    parser_create = subparsers.add_parser('create-event', help='Create a new event')
    parser_create.add_argument('--name', help='Event name')
    parser_create.add_argument('--date', help='Event date (YYYY-MM-DD)')
    parser_create.add_argument('--time-window', help='Time window (e.g., 7-9 PM)')
    parser_create.add_argument('--drop-time', help='Location drop time')
    parser_create.add_argument('--rules', nargs='*', help='House rules')
    parser_create.add_argument('--host-phone', help='Host phone number')
    parser_create.set_defaults(func=create_event_command)

    # send-invites
    parser_invites = subparsers.add_parser('send-invites', help='Send initial invites')
    parser_invites.add_argument('--event-id', type=int, help='Event ID')
    parser_invites.add_argument('--phones', nargs='*', help='Phone numbers to invite')
    parser_invites.set_defaults(func=send_invites_command)

    # handle-message
    parser_message = subparsers.add_parser('handle-message', help='Handle incoming message')
    parser_message.add_argument('--from-phone', required=True, help='Sender phone number')
    parser_message.add_argument('--text', required=True, help='Message text')
    parser_message.add_argument('--event-id', type=int, help='Event ID')
    parser_message.set_defaults(func=handle_message_command)

    # stats
    parser_stats = subparsers.add_parser('stats', help='Show event statistics')
    parser_stats.add_argument('--event-id', type=int, help='Event ID')
    parser_stats.set_defaults(func=stats_command)

    # list
    parser_list = subparsers.add_parser('list', help='Show guest list')
    parser_list.add_argument('--event-id', type=int, help='Event ID')
    parser_list.add_argument('--style', choices=['tree', 'simple', 'stats'], help='List style')
    parser_list.set_defaults(func=list_command)

    # drop-location
    parser_drop = subparsers.add_parser('drop-location', help='Trigger location drop')
    parser_drop.add_argument('--event-id', type=int, help='Event ID')
    parser_drop.add_argument('--address', help='Location address')
    parser_drop.add_argument('--arrival-window', help='Arrival window')
    parser_drop.add_argument('--notes', help='Additional notes')
    parser_drop.set_defaults(func=drop_location_command)

    # Parse args
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Run command
    args.func(args)


if __name__ == '__main__':
    main()
