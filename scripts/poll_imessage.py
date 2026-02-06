#!/usr/bin/env python3
"""
Poll imsg history for new messages and route them to the Flowers bot.
Replaces 'imsg watch' which requires Full Disk Access.
Monitors ALL chats, not just one.
"""

import subprocess
import json
import sys
import os
import time
from expiration_checker import run_expiration_checks

POLL_INTERVAL = 2


def get_all_chats():
    """Fetch all chat IDs from imsg."""
    try:
        result = subprocess.run(
            ["imsg", "chats", "--json"],
            capture_output=True, text=True, timeout=10
        )
        chats = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                chats.append(json.loads(line))
        return chats
    except Exception as e:
        print(f"Error fetching chats: {e}", flush=True)
        return []


def get_recent_messages(chat_id, limit=5):
    """Fetch recent messages from a specific chat."""
    try:
        result = subprocess.run(
            ["imsg", "history", "--chat-id", str(chat_id), "--limit", str(limit), "--json", "--attachments"],
            capture_output=True, text=True, timeout=10
        )
        messages = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                messages.append(json.loads(line))
        return messages
    except Exception as e:
        return []


def get_vcard_path(msg):
    """Extract vCard attachment path from a message, if any."""
    for att in msg.get("attachments", []):
        if att.get("mime_type") == "text/vcard" or (att.get("transfer_name", "").endswith(".vcf")):
            path = att.get("original_path") or att.get("filename", "")
            if path.startswith("~"):
                path = os.path.expanduser(path)
            if os.path.exists(path):
                return path
    return None


def process_message(sender, text, vcard_path=None):
    """Route message through the bot."""
    try:
        cmd = [sys.executable, "scripts/imsg_integration.py", sender, text]
        if vcard_path:
            cmd.extend(["--vcard", vcard_path])
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"✅ Response sent", flush=True)
        else:
            print(f"❌ Error: {result.stderr.strip()}", flush=True)
    except Exception as e:
        print(f"❌ Error handling message: {e}", flush=True)


def get_global_last_id(chats):
    """Get the highest message ID across all chats."""
    max_id = 0
    for chat in chats:
        msgs = get_recent_messages(chat["id"], limit=1)
        if msgs:
            msg_id = msgs[0].get("id", 0)
            if msg_id > max_id:
                max_id = msg_id
    return max_id


def main():
    print("🌸 Flowers Bot - Polling for iMessages...", flush=True)
    print("Press Ctrl+C to stop\n", flush=True)

    # Discover all chats and find the global last message ID
    chats = get_all_chats()
    chat_ids = [c["id"] for c in chats]
    last_id = get_global_last_id(chats)
    print(f"Monitoring {len(chat_ids)} chats, starting from message ID: {last_id}", flush=True)

    while True:
        try:
            # Refresh chat list periodically to pick up new conversations
            chats = get_all_chats()
            chat_ids = [c["id"] for c in chats]

            all_new = []
            for cid in chat_ids:
                messages = get_recent_messages(cid, limit=5)
                for m in messages:
                    if m.get("id", 0) > last_id and not m.get("is_from_me", True):
                        all_new.append(m)

            # Sort by ID (chronological order)
            all_new.sort(key=lambda m: m.get("id", 0))

            for msg in all_new:
                sender = msg.get("sender", "")
                text = msg.get("text", "")
                msg_id = msg.get("id", 0)
                vcard = get_vcard_path(msg)

                if sender and (text or vcard):
                    if not text or text == "\ufffc":
                        text = "(contact card)"
                    print(f"📱 Message from {sender}: {text}", flush=True)
                    process_message(sender, text, vcard_path=vcard)
                    print("", flush=True)

                if msg_id > last_id:
                    last_id = msg_id

            # Also track outgoing message IDs so we don't re-process
            for cid in chat_ids:
                messages = get_recent_messages(cid, limit=1)
                if messages:
                    mid = messages[0].get("id", 0)
                    if mid > last_id:
                        last_id = mid

            # Check for invite and +1 expirations
            run_expiration_checks()

        except KeyboardInterrupt:
            print("\n🌸 Bot stopped.", flush=True)
            break
        except Exception as e:
            print(f"Poll error: {e}", flush=True)

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
