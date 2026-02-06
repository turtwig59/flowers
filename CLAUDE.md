# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Flowers is an iMessage party invite bot. The host creates an event, sends 15 initial invites, each accepted guest can invite exactly 1 friend (+1), and the location is revealed day-of with a two-part dramatic drop (warning message, then address 5 minutes later). The bot runs as a background process polling for iMessages via the `imsg` CLI tool.

## Commands

```bash
# Run all tests (MUST use FLOWERS_TESTING=1 to prevent real iMessage sends)
FLOWERS_TESTING=1 pytest tests/ -v

# Run a specific test file
FLOWERS_TESTING=1 pytest tests/test_conversation_flows.py -v

# Run a specific test
FLOWERS_TESTING=1 pytest tests/test_conversation_flows.py::TestFullInviteFlow::test_happy_path -v

# Initialize database
python3 scripts/bot.py init

# Start the bot (background iMessage poller)
./scripts/watch_imessage.sh &
echo $! > /tmp/flowers-bot.pid

# Stop the bot
kill $(cat /tmp/flowers-bot.pid)

# View logs
tail -f ~/flowers-bot.log
```

**Dependencies:** `pip3 install pytest phonenumbers python-dateutil anthropic python-dotenv`

## CRITICAL: Never Send Real Messages Without Permission

- NEVER run `imsg_integration.py`, `imsg send`, or any command that sends iMessages without explicit user approval
- To test bot logic, use `FLOWERS_TESTING=1 pytest` or call Python functions directly (e.g., `parse_date()`, `route_message()`) without the send layer
- The `FLOWERS_TESTING` env var is set automatically by `tests/conftest.py`, but always verify
- The bot running in background sends real messages — be careful about starting it during development

## Architecture

### Message Flow

```
iMessage → poll_imessage.py (polls imsg history) → imsg_integration.py → message_router.py → handler → response → imsg send
```

`watch_imessage.sh` is the entry point. It launches `poll_imessage.py`, which polls ALL chats every 2 seconds via `imsg history`. When a new message is detected, it calls `imsg_integration.py` with the sender phone, message text, and optional `--vcard <path>` for contact card attachments. `imsg_integration.py` calls `route_message()` and sends the response back via `imsg send`.

### Message Routing (`message_router.py`)

The router is the central dispatch. Order of precedence:
1. **Event creation flow** — if host is mid-creation, routes to `event_creation.py`
2. **"create event"** keyword — starts new creation flow
3. **Host detection** — if sender matches `event.host_phone`, routes to `host_commands.py`
4. **Unknown guest** — rejects if phone not in guest list
5. **FAQ detection** — regex patterns match location/time/+1 questions (handled in any state)
6. **State-based routing** — dispatches to `guest_handlers.py` based on conversation state
7. **LLM Q&A** — idle-state messages routed to `llm_responder.py` for Claude-powered answers
8. **Question escalation** — if LLM returns `[ESCALATE]`, question is forwarded to host

### State Machine (Guests)

States stored in `conversation_state` table, keyed by `(event_id, phone)`:

```
waiting_for_response → (YES) → waiting_for_name → waiting_for_instagram → waiting_for_plus_one → (YES) → waiting_for_contact → idle
                     → (NO)  → idle (declined)                                                 → (NO)  → idle
```

### Event Creation Flow (Host)

Uses `event_id = 0` in `conversation_state` as a sentinel for in-progress creation:

```
creating_event_name → creating_event_date → creating_event_time → creating_event_drop_time → creating_event_rules → (event created)
```

- Event names capped at 50 characters
- Dates parsed flexibly via `python-dateutil` (accepts "Feb 14", "2/14", "next friday", "tomorrow", "the 20th", etc.)

### Two-Tier Parsing (Regex + LLM Fallback)

Every conversation handler follows this pattern:
1. **Regex first** — fast pattern matching for common responses (YES_PATTERNS, NO_PATTERNS, etc.)
2. **LLM fallback** — if regex doesn't match, `llm_responder.parse_message()` uses Claude Haiku to interpret casual text ("bet", "say less", "im down", "nah maybe next time")

This applies to: yes/no responses, name extraction, Instagram handles, +1 decisions, and contact submission.

### Question Escalation Flow

When a confirmed guest asks a question the LLM can't answer:
1. LLM returns `[ESCALATE] <summary>`
2. Bot tells guest "Let me check on that for you."
3. Bot texts host: `"<Guest> asked: '<question>'\nReply and I'll pass it along."`
4. Host's conversation state set to `answering_guest_question`
5. When host replies, answer is rewritten in doorman voice via `rewrite_host_answer()` and sent to guest

### vCard / Contact Card Support

iMessage contact cards arrive as attachments with `mime_type: "text/vcard"` and a `.vcf` file path. The pipeline:
1. `poll_imessage.py` detects vCard attachments in message data
2. Passes file path via `--vcard` flag to `imsg_integration.py`
3. `route_message()` parses the vCard via `parse_vcard_file()`
4. For **hosts**: vCard treated as invite (extracts phone, sends invite)
5. For **guests** (`waiting_for_contact` or `waiting_for_plus_one`): vCard treated as +1 contact submission

### Key Modules

- **`bot.py`** — CLI entry point (argparse with 7 subcommands)
- **`db.py`** — SQLite wrapper; singleton `db` instance used everywhere via `from db import db`
- **`message_router.py`** — Central dispatch; regex-based intent detection + LLM fallback + question escalation
- **`guest_handlers.py`** — State machine handlers for guest conversation flow (including Instagram collection)
- **`host_commands.py`** — Host commands: list, stats, search, drop location, send invites, answer escalated questions
- **`event_creation.py`** — Multi-step conversational event creation with flexible date parsing
- **`location_drop.py`** — Two-part location reveal with `threading.Timer` for the 5-minute delay
- **`invite_sender.py`** — Sends invite messages with doorman intro and creates guest/state records
- **`imsg_integration.py`** — Bridge between `imsg` CLI and bot logic; accepts `--vcard` flag
- **`poll_imessage.py`** — Polls ALL iMessage chats every 2 seconds via `imsg history` (replaced `imsg watch`)
- **`llm_responder.py`** — Claude Haiku integration: Q&A (doorman persona), message parsing fallback, host answer rewriting
- **`contacts_util.py`** — Adds/updates macOS Contacts via AppleScript when guests provide names
- **`phone_utils.py`** — E.164 normalization via `phonenumbers` library
- **`contact_parser.py`** — vCard parsing and name extraction from free text
- **`daily_log.py`** — Appends human-readable markdown logs to `data/memory/YYYY-MM-DD.md`

### Database

SQLite at `data/flowers.db`. Schema in `scripts/init_db.py`. Four tables:
- **events** — event details, host_phone, status, rules (JSON)
- **guests** — phone (E.164), name, instagram, status, invited_by_phone (invite tree), quota_used (0 or 1)
- **conversation_state** — current state + context (JSON), keyed by (event_id, phone)
- **message_log** — full audit trail of all messages

Quota enforcement uses atomic transactions in `db.use_quota()` plus a SQLite trigger as backup.

### Testing

Tests use `tests/mock_imsg.py` to mock iMessage sending. `tests/conftest.py` auto-sets `FLOWERS_TESTING=1` to prevent real sends. All scripts run from the `scripts/` directory and import each other as siblings (no package structure).

### Important: `imsg` CLI Syntax

```bash
imsg send --to "yed.flowers@icloud.com" --text "message"
imsg history --chat-id <id> --limit <n> --json --attachments
imsg chats --json
```

Uses `--to` and `--text` flags (not positional arguments).

### Environment

- **Anthropic API key** stored in `.env` file at project root, loaded via `python-dotenv`
- **`FLOWERS_TESTING`** env var — when set, prevents real iMessage sends in `invite_sender.py` and `location_drop.py`

## Troubleshooting

### `imsg watch` Not Receiving Messages

We switched from `imsg watch` to polling via `poll_imessage.py` because `imsg watch` requires Full Disk Access and was unreliable. The poller uses `imsg history` every 2 seconds and works without Full Disk Access issues.

### Bot Not Picking Up Guest Responses

The poller must monitor ALL chat IDs (not just the host's). `poll_imessage.py` calls `imsg chats --json` to discover all conversations and polls each one.

## Conventions

- All phone numbers normalized to E.164 format before storage/comparison
- Bot persona: "Yed" the digital doorman — short, confident, NYC energy
- Doorman intro for new guests: "I'm Yed — digital doorman. Someone put you on the list."
- Bot responses follow conversational tone: concise (2-3 sentences), no technical jargon, always offer next steps
- End-of-flow messages include "Got questions about the event? Just ask."
- Logging errors are silently caught (`except: pass`) to never break message handling
- The `db` singleton is imported directly: `from db import db`
- Circular imports between `message_router.py` and handler modules are resolved with local imports inside functions
