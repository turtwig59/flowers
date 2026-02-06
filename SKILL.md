---
name: flowers
description: iMessage party invite bot managing cascading invitations with +1 system, conversational Q&A, and location drops
user-invocable: false
---

# Flowers - Party Invite Bot

An iMessage bot that manages exclusive party invitations with a cascading +1 system. The host sends 15 initial invites, and each confirmed guest can invite exactly one friend, creating a controlled viral guest list.

## Core Capabilities

- **Cascading Invites**: Host → 15 people → each can invite 1 friend
- **Conversational Flow**: Natural Q&A with guests about the event
- **Name Collection**: Collects guest names after they accept
- **Strict Quota Enforcement**: Exactly 1 invite per confirmed guest
- **Host-Only Guest List**: Search, stats, and full tree view
- **Location Drop Ritual**: Two-part reveal with 5-minute timing

## When to Use This Bot

Use this bot when the user:
- Wants to create or manage a party/event
- Needs to send invites via iMessage
- Wants to view guest lists or statistics
- Is ready to trigger the location drop
- Receives an iMessage related to an event

## Bot Tone & Style

**Principles:**
- Concise (2-3 sentences max)
- Human, not robotic
- No technical jargon
- Always offer next steps

**Key Phrases:**
- "Reply YES to confirm or NO to decline"
- "Send me a contact card or phone number"
- "You get one invite to share"
- "What's your name?"
- "Location drops at [time] on the day of"

**Never Say:**
- "Command", "slash", "type /help"
- "API", "database", "system"
- Technical error messages

## Usage Examples

### For the Host

**Creating an Event:**
```bash
python3 scripts/bot.py create-event \
  --name "Spring Garden Party" \
  --date "2026-03-15" \
  --time-window "7-9 PM" \
  --drop-time "6:30 PM" \
  --rules "No photos" "Dress code: Garden chic" \
  --host-phone "+15551234567"
```

**Sending Initial Invites:**
```bash
python3 scripts/bot.py send-invites \
  --phones "+15551111111" "+15552222222" "+15553333333"
```

Or interactively:
```bash
python3 scripts/bot.py send-invites
```

**Viewing Guest List:**
```bash
python3 scripts/bot.py list
# Tree view with invite relationships

python3 scripts/bot.py list --style simple
# Simple confirmed-only list

python3 scripts/bot.py stats
# Statistics summary
```

**Triggering Location Drop:**
```bash
python3 scripts/bot.py drop-location \
  --address "123 Main St, Brooklyn NY" \
  --arrival-window "2-5 PM" \
  --notes "Ring doorbell twice"
```

### For Guests (via iMessage)

**Accepting Invite:**
```
Guest: YES
Bot: Great! What's your name?
Guest: Alice
Bot: You get one invite to share. Want to invite someone?
Guest: Yes
Bot: Send me a contact card or their phone number.
Guest: [sends contact card]
Bot: Invite sent! I'll let you know when they respond.
```

**Asking Questions:**
```
Guest: Where is this?
Bot: Location drops at 6:30 PM on the day of.

Guest: Can I bring someone?
Bot: You get one invite to share! Want to invite someone now?
```

**Declining:**
```
Guest: NO
Bot: Thanks for letting me know!
```

## OpenClaw Integration

### Message Handling

When an iMessage arrives for an active event, route it to the bot:

```bash
python3 scripts/bot.py handle-message \
  --from-phone "+15551234567" \
  --text "YES"
```

The bot will:
1. Identify if sender is host or guest
2. Check conversation state
3. Route to appropriate handler
4. Return response text
5. Log to database

### Host Commands via iMessage

The bot recognizes these patterns from the host phone:

- "list" or "guest list" → Show full guest list
- "stats" → Show statistics
- "search [name]" → Find specific guest
- "drop location" → Initiate location drop flow
- Phone numbers → Send invites

### Response Handling

After calling `handle-message`, send the returned response back via iMessage:

```python
response = bot_handle_message(from_phone, text)
imsg.send(to=from_phone, text=response)
```

## Architecture

```
Bot receives message
    ↓
Normalize phone to E.164
    ↓
Is host? → Handle host command
    ↓
Is guest? → Check conversation state
    ↓
Route to state machine handler
    ↓
Update database & state
    ↓
Return response
```

## Database

SQLite at `data/flowers.db`:
- **events**: Party details, host, rules
- **guests**: Phone, name, status, quota, invite tree
- **conversation_state**: Current state in flow
- **message_log**: Audit trail

## State Machine

Guest conversation states:
- `waiting_for_response` → After invite sent
- `waiting_for_name` → After accepting
- `waiting_for_plus_one` → After providing name
- `waiting_for_contact` → After accepting +1 offer
- `idle` → Can answer FAQ questions

## Quota Enforcement

Each confirmed guest has `quota_used` (0 or 1):
- ✅ Can invite: `status='confirmed'` AND `quota_used=0`
- ❌ Already used: `quota_used=1`
- ❌ Not eligible: `status='pending'` or `status='declined'`

Database-level locking prevents race conditions:
```sql
SELECT ... FOR UPDATE  -- Lock row during invite
UPDATE guests SET quota_used = 1  -- Atomic increment
```

## Location Drop

Two-part message with 5-minute delay:

**Part 1 (immediate):**
> 🎉 Spring Garden Party
>
> Location drops in 5 minutes.
> Get ready!

**Part 2 (after 5 minutes):**
> 📍 Spring Garden Party
>
> 123 Main St, Brooklyn NY
> Arrival: 2-5 PM
>
> Ring doorbell twice
>
> See you there!

Sent only to `status='confirmed'` guests.

## Memory & Logging

Daily logs at `data/memory/YYYY-MM-DD.md`:
- Significant events (invites sent, acceptances)
- Location drops
- Statistics snapshots
- Human-readable format

## Testing

Run the test suite:
```bash
pytest tests/ -v

# 54 tests covering:
# - Phone normalization
# - Database operations
# - Full conversation flows
# - Location drop timing
```

## Safety Features

- Phone numbers validated and normalized (E.164)
- Host authentication (exact phone match)
- Quota enforcement (database-level)
- No destructive operations without confirmation
- All messages logged for audit

## Common Scenarios

### Scenario 1: Guest accepts and invites +1
```
1. Bot sends invite to Alice
2. Alice: "YES"
3. Bot: "Great! What's your name?"
4. Alice: "Alice"
5. Bot: "You get one invite to share. Want to invite someone?"
6. Alice: "Yes"
7. Bot: "Send me a contact card or their phone number."
8. Alice: [sends Bob's number]
9. Bot: "Invite sent! I'll let you know when they respond."
10. Bot sends invite to Bob (attributed to Alice)
```

### Scenario 2: Host triggers location drop
```
1. Host: "drop location"
2. Bot: "Ready to drop location to 12 confirmed guests..."
3. Host: "123 Main St | 2-5 PM | Be cool"
4. Bot: "Location drop initiated! 🎉 Sending to 12 confirmed guests..."
5. Bot sends warning to all confirmed guests
6. (5 minutes later) Bot sends address to all confirmed guests
```

### Scenario 3: Guest asks FAQ
```
Guest: "Where is this?"
Bot: "Location drops at 6:30 PM on the day of."

Guest: "Can I bring someone?"
Bot: "You get one invite to share after you confirm."
```

## Troubleshooting

**No active event:**
```bash
python3 scripts/bot.py create-event
```

**Guest not recognized:**
- Check if they've been invited: `python3 scripts/bot.py list`
- Phone number must match exactly (E.164 format)

**Quota not enforcing:**
- Check database: `SELECT * FROM guests WHERE quota_used = 1`
- Verify row locking is working (should never have >1 +1 per guest)

**Location drop not sending:**
- Verify confirmed guests: `python3 scripts/bot.py stats`
- Check threading timer is active
- Review message_log table

## Files

**Core:**
- `scripts/bot.py` - Main CLI and orchestrator
- `scripts/db.py` - Database operations
- `scripts/message_router.py` - Routes messages to handlers
- `scripts/guest_handlers.py` - Guest conversation state machine
- `scripts/host_commands.py` - Host command handlers
- `scripts/location_drop.py` - Location drop orchestration

**Utilities:**
- `scripts/phone_utils.py` - Phone normalization (E.164)
- `scripts/contact_parser.py` - vCard parsing
- `scripts/invite_sender.py` - Send invites with proper messaging

**Tests:**
- `tests/test_phone_utils.py` - Phone number handling
- `tests/test_db.py` - Database operations
- `tests/test_conversation_flows.py` - Full conversation flows
- `tests/test_location_drop.py` - Location drop timing

**Data:**
- `data/flowers.db` - SQLite database
- `data/memory/` - Daily conversation logs

## Quick Reference

```bash
# Initialize
python3 scripts/bot.py init

# Create event
python3 scripts/bot.py create-event

# Send invites
python3 scripts/bot.py send-invites --phones "+15551111111" "+15552222222"

# Handle message
python3 scripts/bot.py handle-message --from-phone "+15551111111" --text "YES"

# View list
python3 scripts/bot.py list

# Stats
python3 scripts/bot.py stats

# Drop location
python3 scripts/bot.py drop-location
```

## Success Metrics

- ✅ Host can create event and send 15 invites in < 2 minutes
- ✅ Guests receive and can respond naturally
- ✅ Conversation feels human and flows smoothly
- ✅ Quota enforcement is bulletproof
- ✅ Location drop executes precisely with timing
- ✅ All messages match tone guidelines
