# Flowers 🌸

An iMessage party invite bot that manages cascading invitations with a +1 system. Perfect for exclusive events where you want controlled viral growth of your guest list.

## Overview

**The Concept:**
- Host sends 15 initial invites
- Each person who accepts can invite up to 2 friends
- Bot manages the entire flow conversationally
- Location revealed day-of with a dramatic two-part drop

**The Experience:**
- Natural conversation (no commands, just texting)
- Collects names after acceptance
- Answers questions ("where?", "when?", "can I bring someone?")
- Strict quota enforcement (bulletproof)
- Host has full visibility and control

## Features

### For Guests
- ✅ Simple YES/NO responses
- ✅ Natural Q&A about the event
- ✅ Two invites to share
- ✅ Contact card or phone number submission
- ✅ Location drop ritual (warning → 5 min → address)

### For Host
- ✅ Create events with details
- ✅ Send initial 15 invites
- ✅ View guest list (tree view showing invite relationships)
- ✅ Search guests by name
- ✅ Real-time statistics
- ✅ Trigger location drop
- ✅ Full audit trail

## Quick Start

### 1. Install Dependencies

```bash
pip3 install pytest phonenumbers
```

### 2. Initialize Database

```bash
python3 scripts/bot.py init
```

### 3. Create Your Event

```bash
python3 scripts/bot.py create-event \
  --name "Spring Garden Party" \
  --date "2026-03-15" \
  --time-window "7-9 PM" \
  --drop-time "6:30 PM" \
  --rules "No photos" "Dress code: Garden chic" \
  --host-phone "+15551234567"
```

Or run interactively:
```bash
python3 scripts/bot.py create-event
```

### 4. Send Initial Invites

```bash
python3 scripts/bot.py send-invites \
  --phones "+15551111111" "+15552222222" "+15553333333"
```

### 5. Handle Messages

When you receive an iMessage, process it:

```bash
python3 scripts/bot.py handle-message \
  --from-phone "+15551111111" \
  --text "YES"
```

The bot returns the response text, which you send back via iMessage.

## CLI Commands

### Event Management

```bash
# Create event (interactive)
python3 scripts/bot.py create-event

# Create event (command line)
python3 scripts/bot.py create-event \
  --name "Party Name" \
  --date "2026-03-15" \
  --time-window "7-9 PM" \
  --drop-time "6:30 PM" \
  --host-phone "+15551234567"
```

### Invitations

```bash
# Send invites (interactive)
python3 scripts/bot.py send-invites

# Send invites (command line)
python3 scripts/bot.py send-invites --phones "+1555..." "+1555..."
```

### Guest List

```bash
# Tree view (shows invite relationships)
python3 scripts/bot.py list

# Simple view (confirmed only)
python3 scripts/bot.py list --style simple

# Statistics
python3 scripts/bot.py stats
```

### Location Drop

```bash
# Interactive
python3 scripts/bot.py drop-location

# Command line
python3 scripts/bot.py drop-location \
  --address "123 Main St, Brooklyn NY" \
  --arrival-window "2-5 PM" \
  --notes "Ring doorbell twice"
```

## Conversation Examples

### Guest Accepting Invite

```
Bot: You're invited to Spring Garden Party on Saturday, March 15, 7-9 PM.
     Reply YES to confirm or NO to decline.

Guest: YES

Bot: Great! What's your name?

Guest: Alice

Bot: You get two invites to share. Want to invite someone?

Guest: Yes please

Bot: Send me a contact card or their phone number.

Guest: [sends contact card for Bob]

Bot: Invite sent! I'll let you know when they respond.

     You have one more invite. Want to invite someone else?
```

### Guest Asking Questions

```
Guest: Where is this?

Bot: Location drops at 6:30 PM on the day of.

Guest: Can I bring someone?

Bot: You get two invites to share! Want to invite someone now?
```

### Host Managing Event

```
Host: list

Bot: 📋 Spring Garden Party

     ✅ Alice
       └─ ✅ Bob
     ⏳ Charlie
     ✅ Diana
       └─ ⏳ Eve

Host: stats

Bot: 📊 Spring Garden Party

     ✅ Confirmed: 3
     ⏳ Pending: 2
     ❌ Declined: 0
     📥 Total invited: 5
     ➕ +1s used: 2

Host: search Alice

Bot: 🔍 Results for 'Alice':

     ✅ Alice (initial invite) · invites 2/2
```

## Architecture

### Project Structure

```
flowers/
├── SKILL.md              # OpenClaw skill definition
├── README.md             # This file
├── scripts/
│   ├── bot.py            # Main CLI orchestrator
│   ├── db.py             # Database operations
│   ├── phone_utils.py    # Phone normalization
│   ├── message_router.py # Message routing logic
│   ├── guest_handlers.py # Guest conversation state machine
│   ├── host_commands.py  # Host command handlers
│   ├── location_drop.py  # Location drop orchestration
│   ├── invite_sender.py  # Send invites
│   └── contact_parser.py # vCard parsing
├── tests/
│   ├── test_phone_utils.py
│   ├── test_db.py
│   ├── test_conversation_flows.py
│   └── test_location_drop.py
└── data/
    ├── flowers.db        # SQLite database
    └── memory/           # Daily conversation logs
```

### Database Schema

**events**
- Event details (name, date, time, host)
- Location drop time
- House rules

**guests**
- Phone (E.164 normalized)
- Name (collected after acceptance)
- Status (pending/confirmed/declined)
- Invite tree (invited_by_phone)
- Quota tracking (0, 1, or 2)

**conversation_state**
- Current state in conversation flow
- Context data (JSON)
- Last message timestamp

**message_log**
- Full audit trail
- Inbound/outbound direction
- Timestamps

### State Machine

```
pending (created)
    ↓
waiting_for_response (invite sent)
    ↓ YES
waiting_for_name (accepted)
    ↓ name provided
waiting_for_plus_one (offer +1)
    ↓ accepts +1 offer
waiting_for_contact (submit phone/contact)
    ↓ contact processed
idle (can answer FAQ)
```

## Testing

Run the full test suite:

```bash
pytest tests/ -v
```

**54 tests covering:**
- Phone number normalization (15 tests)
- Database operations (14 tests)
- Full conversation flows (13 tests)
- Location drop timing (12 tests)

## OpenClaw Integration

### Setup

1. Install OpenClaw and configure iMessage channel
2. Point OpenClaw to the Flowers skill directory
3. Configure message routing to call `bot.py handle-message`

### Message Flow

```
iMessage arrives
    ↓
OpenClaw receives via imsg CLI
    ↓
Routes to Flowers bot
    ↓
bot.py handle-message --from-phone ... --text ...
    ↓
Returns response text
    ↓
OpenClaw sends via imsg
```

See `SKILL.md` for complete OpenClaw integration guide.

## Design Decisions

### Why E.164 Phone Format?
Ensures consistent identity across different input formats:
- `(555) 123-4567` → `+15551234567`
- `555-123-4567` → `+15551234567`
- All database lookups use normalized format

### Why Database-Level Quota Enforcement?
Prevents race conditions when guests try to invite multiple people:
- Row-level locking (`SELECT ... FOR UPDATE`)
- Atomic quota increment
- Database trigger as backup

### Why Two-Part Location Drop?
Creates anticipation and gives everyone time to prepare:
- Part 1: "Location drops in 5 minutes" (builds excitement)
- Part 2: Actual address (5 minutes later)

### Why Conversational State Machine?
Makes the flow predictable and debuggable:
- Each state has clear transitions
- Easy to add new flows
- Testable in isolation

## Tone Guidelines

**Principles:**
- Concise (2-3 sentences max)
- Human, not robotic
- No technical jargon
- Always offer next steps

**Say This:**
- "Reply YES to confirm"
- "Send me a contact card"
- "You get two invites to share"
- "What's your name?"

**Not This:**
- "Please execute the accept command"
- "Error: Invalid phone number format"
- "Type /help for more information"

## Troubleshooting

### Guest not recognized
```bash
# Check if they've been invited
python3 scripts/bot.py list

# Phone number must match exactly (E.164)
```

### Quota not enforcing
```bash
# Check database
sqlite3 data/flowers.db "SELECT * FROM guests WHERE quota_used > 0"

# Should never have quota_used > 2
```

### Location drop not sending
```bash
# Verify confirmed guests exist
python3 scripts/bot.py stats

# Check message_log table
sqlite3 data/flowers.db "SELECT * FROM message_log ORDER BY timestamp DESC LIMIT 10"
```

## Contributing

### Running Tests
```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_conversation_flows.py -v

# Specific test
pytest tests/test_conversation_flows.py::TestFullInviteFlow::test_happy_path -v
```

### Adding New Features

1. Update database schema in `scripts/init_db.py`
2. Add database operations in `scripts/db.py`
3. Add handler logic in appropriate module
4. Write tests
5. Update documentation

## License

MIT

## Credits

Built with:
- Python 3.9+
- SQLite
- phonenumbers library
- pytest

Designed for use with OpenClaw and iMessage.
