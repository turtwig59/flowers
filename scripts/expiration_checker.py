"""
Expiration checker for invite and +1 time limits.
Guests have 1 hour to respond to invites, and 1 hour to use their +1 invites.
Warnings are sent at 45 minutes, expiration at 60 minutes.
"""

import os
import time
from db import db

INVITE_WARNING_SECONDS = 2700   # 45 minutes
INVITE_EXPIRE_SECONDS = 3600    # 60 minutes
PLUS_ONE_WARNING_SECONDS = 2700
PLUS_ONE_EXPIRE_SECONDS = 3600

# Only apply expiration to guests invited after this feature was deployed.
# Prevents retroactive expiration of pre-existing guests.
FEATURE_DEPLOY_TIME = 1770396900

# Onboarding states where guest hasn't finished setup yet
ONBOARDING_STATES = ('waiting_for_name', 'waiting_for_instagram')


def _send_message(phone, text):
    """Send an iMessage, no-op in testing mode."""
    if os.environ.get('FLOWERS_TESTING'):
        return
    try:
        from imsg_integration import send_imessage
        send_imessage(phone, text)
    except Exception:
        pass


def _refund_inviter(event_id, expired_guest):
    """Refund an invite to the person who invited the expired guest."""
    inviter_phone = expired_guest.get('invited_by_phone')
    if not inviter_phone:
        return  # Host invite — no one to refund

    inviter = db.get_guest_by_phone(inviter_phone, event_id)
    if not inviter or inviter['quota_used'] <= 0:
        return

    db.update_guest(inviter['id'], quota_used=inviter['quota_used'] - 1)
    inviter_name = expired_guest.get('name') or expired_guest['phone']
    _send_message(inviter_phone,
                  f"Your invite to {inviter_name} expired. You've got another invite to give.")


def check_invite_expirations():
    """Check for expired invites and send warnings/expiry messages."""
    event = db.get_active_event()
    if not event:
        return

    event_id = event['id']
    now = int(time.time())

    # Get all pending guests
    pending_guests = db.get_guests(event_id, status='pending')

    for guest in pending_guests:
        invited_at = guest['invited_at']
        if invited_at < FEATURE_DEPLOY_TIME:
            continue

        state_record = db.get_conversation_state(event_id, guest['phone'])
        if not state_record or state_record['state'] != 'waiting_for_response':
            continue
        elapsed = now - invited_at
        context = state_record.get('context', {}) or {}

        if elapsed >= INVITE_EXPIRE_SECONDS:
            # Re-read guest to guard against race condition (guest responded between query and now)
            fresh_guest = db.get_guest(guest['id'])
            if not fresh_guest or fresh_guest['status'] != 'pending':
                continue

            # Expire the invite
            db.update_guest(guest['id'], status='expired')
            db.upsert_conversation_state(event_id, guest['phone'], 'idle', {'expired': True})
            _send_message(guest['phone'], "Your invite expired. Maybe next time.")

            # Refund the inviter's quota if this was a +1 invite
            _refund_inviter(event_id, fresh_guest)

        elif elapsed >= INVITE_WARNING_SECONDS and not context.get('invite_warning_sent'):
            # Send warning
            _send_message(guest['phone'], "Hey, your invite expires in 15 minutes. You in?")
            db.merge_conversation_context(event_id, guest['phone'], {'invite_warning_sent': True})


def check_plus_one_expirations():
    """Check for expired +1 invite windows and send warnings/expiry messages."""
    event = db.get_active_event()
    if not event:
        return

    event_id = event['id']
    now = int(time.time())

    # Get confirmed guests who haven't used all their invites
    confirmed_guests = db.get_guests(event_id, status='confirmed')

    for guest in confirmed_guests:
        if guest['quota_used'] >= 2:
            continue

        responded_at = guest.get('responded_at')
        if not responded_at:
            continue

        if responded_at < FEATURE_DEPLOY_TIME:
            continue

        elapsed = now - responded_at
        if elapsed < PLUS_ONE_WARNING_SECONDS:
            continue

        state_record = db.get_conversation_state(event_id, guest['phone'])
        state = state_record['state'] if state_record else 'idle'
        context = (state_record.get('context', {}) or {}) if state_record else {}

        if elapsed >= PLUS_ONE_EXPIRE_SECONDS:
            # Revoke remaining invites
            db.update_guest(guest['id'], quota_used=2)

            if state in ('waiting_for_plus_one', 'waiting_for_contact', 'idle'):
                # Guest is past onboarding — send expiry message
                _send_message(guest['phone'], "Time's up on your invites. They've been revoked.")
                db.upsert_conversation_state(event_id, guest['phone'], 'idle',
                                             {'plus_one_expired': True})
            # If still in onboarding (waiting_for_name, waiting_for_instagram),
            # silently revoke — no message, don't change state

        elif elapsed >= PLUS_ONE_WARNING_SECONDS and not context.get('plus_one_warning_sent'):
            # Only warn if past onboarding
            if state not in ONBOARDING_STATES:
                _send_message(guest['phone'], "You've got 15 minutes left to use your invites.")
                db.merge_conversation_context(event_id, guest['phone'],
                                              {'plus_one_warning_sent': True})


def run_expiration_checks():
    """Run all expiration checks. Each is wrapped so one failing doesn't block the other."""
    try:
        check_invite_expirations()
    except Exception:
        pass

    try:
        check_plus_one_expirations()
    except Exception:
        pass
