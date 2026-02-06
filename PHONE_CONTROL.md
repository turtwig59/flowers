# Control Flowers Bot from Your Phone

Complete guide to controlling the bot via iMessage from your phone.

## Prerequisites

1. **Install imsg CLI**
   ```bash
   brew install imsg
   ```

2. **Grant Permissions**
   - Go to System Settings → Privacy & Security → Full Disk Access
   - Add Terminal (or your terminal app)
   - Go to System Settings → Privacy & Security → Automation
   - Allow Terminal to control Messages

3. **Verify imsg works**
   ```bash
   imsg chats
   ```

## Setup

### Option 1: Automatic (Recommended)

Run the watcher script to automatically handle all incoming messages:

```bash
cd /Users/yed/Documents/flowers
./scripts/watch_imessage.sh
```

This will:
- Monitor all incoming iMessages
- Automatically route them to the bot
- Send responses back
- Keep running until you press Ctrl+C

**To run in background:**
```bash
nohup ./scripts/watch_imessage.sh > bot.log 2>&1 &
```

**To stop background process:**
```bash
pkill -f watch_imessage.sh
```

### Option 2: Manual (For Testing)

Process a single message manually:

```bash
python3 scripts/imsg_integration.py "+15551234567" "YES"
```

## Using the Bot from Your Phone

Once the watcher is running, you can text the bot from your phone!

### As a Guest

**Accept invite:**
```
You: YES
Bot: Great! What's your name?

You: Alice
Bot: You get two invites to share. Want to invite someone?

You: Yes
Bot: Send me a contact card or their phone number.

You: +15559999999
Bot: Invite sent! I'll let you know when they respond.
```

**Ask questions:**
```
You: Where is this?
Bot: Location drops at 6:30 PM on the day of.

You: Can I bring someone?
Bot: You get two invites to share! Want to invite someone now?
```

### As the Host

**View guest list:**
```
You: list
Bot: 📋 Spring Garden Party
     ✅ Alice
       └─ ✅ Bob
     ⏳ Charlie
```

**Get statistics:**
```
You: stats
Bot: 📊 Spring Garden Party
     ✅ Confirmed: 3
     ⏳ Pending: 2
     ❌ Declined: 0
```

**Search for someone:**
```
You: search Alice
Bot: 🔍 Results for 'Alice':
     ✅ Alice (initial invite) · invites 2/2
```

**Trigger location drop:**
```
You: drop location
Bot: Ready to drop location to 5 confirmed guests.
     Before I send it:
     1. What's the address?
     2. Any arrival window?
     3. Any last notes?

     Reply with: [address] | [arrival window] | [notes]

You: 123 Main St, Brooklyn | 2-5 PM | Ring doorbell
Bot: Location drop initiated! 🎉
     Sending to 5 confirmed guests:
     • Part 1: "Location drops in 5 minutes" (sent now)
     • Part 2: Address reveal (in 5 minutes)
```

**Send invites by phone number:**
```
You: +15551111111
     +15552222222
     +15553333333
Bot: Sent 3 invites.
```

## Starting the Bot

### Quick Start
```bash
# 1. Create your event (one-time)
python3 scripts/bot.py create-event

# 2. Start watching for messages
./scripts/watch_imessage.sh
```

Now just text the bot from your phone!

### Keep It Running

To have the bot always running in the background:

1. **Start in background:**
   ```bash
   cd /Users/yed/Documents/flowers
   nohup ./scripts/watch_imessage.sh > ~/flowers-bot.log 2>&1 &
   echo $! > ~/flowers-bot.pid
   ```

2. **Check if running:**
   ```bash
   ps aux | grep watch_imessage
   # or
   tail -f ~/flowers-bot.log
   ```

3. **Stop the bot:**
   ```bash
   kill $(cat ~/flowers-bot.pid)
   rm ~/flowers-bot.pid
   ```

### Auto-start on Login (Optional)

Create a LaunchAgent to start the bot automatically:

```bash
# Create the plist file
cat > ~/Library/LaunchAgents/com.flowers.bot.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.flowers.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/yed/Documents/flowers/scripts/watch_imessage.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/yed/flowers-bot.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yed/flowers-bot-error.log</string>
</dict>
</plist>
EOF

# Load it
launchctl load ~/Library/LaunchAgents/com.flowers.bot.plist

# Unload if needed
# launchctl unload ~/Library/LaunchAgents/com.flowers.bot.plist
```

## Troubleshooting

### Messages not being received

1. **Check if imsg watch is working:**
   ```bash
   imsg watch --json
   ```
   Send yourself a test message and see if it appears.

2. **Check permissions:**
   - Full Disk Access for Terminal
   - Automation permission for Messages

3. **Check the bot is running:**
   ```bash
   ps aux | grep watch_imessage
   ```

### Messages received but no response

1. **Check for errors:**
   ```bash
   tail -f ~/flowers-bot.log  # if running in background
   ```

2. **Test manually:**
   ```bash
   python3 scripts/imsg_integration.py "YOUR_PHONE" "test"
   ```

3. **Check active event:**
   ```bash
   python3 scripts/bot.py stats
   ```

### Bot crashes

Check the logs:
```bash
tail -100 ~/flowers-bot.log
tail -100 ~/flowers-bot-error.log  # if using LaunchAgent
```

## Tips

1. **Keep your Mac awake** - The bot needs to be running on your Mac
2. **WiFi/Internet required** - For iMessage to work
3. **Test with yourself first** - Send messages to the bot from your phone to test
4. **Check logs regularly** - Monitor `~/flowers-bot.log`
5. **One event at a time** - The bot focuses on the active event

## Example Complete Flow

```bash
# 1. Create event
python3 scripts/bot.py create-event

# 2. Start bot
./scripts/watch_imessage.sh

# 3. From your phone, send invites:
Text: "+15551111111"
Text: "+15552222222"

# 4. Check status:
Text: "stats"

# 5. When ready:
Text: "drop location"
Text: "123 Main St | 2-5 PM | Be cool"
```

## Security Notes

- Bot only responds to configured host phone number for commands
- All guests can only perform limited actions (accept, name, +1)
- All messages logged to database
- No sensitive data stored in logs
- Phone numbers normalized and validated

## Next Steps

1. Create your first event
2. Start the watcher
3. Text the bot from your phone to test
4. Send real invites when ready!
