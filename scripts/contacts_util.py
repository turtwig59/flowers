"""
macOS Contacts integration.
Adds or updates contacts when the bot learns a guest's name.
"""

import os
import subprocess


def upsert_contact(phone: str, name: str):
    """
    Add or update a contact on macOS by phone number.

    If a contact with this phone exists, update the name.
    If not, create a new contact.

    Args:
        phone: Phone number (E.164 format)
        name: Full name
    """
    if os.environ.get('FLOWERS_TESTING'):
        return

    parts = name.strip().split(None, 1)
    first_name = parts[0] if parts else name
    last_name = parts[1] if len(parts) > 1 else ""

    # Escape for AppleScript
    first_name = first_name.replace('"', '\\"')
    last_name = last_name.replace('"', '\\"')
    phone = phone.replace('"', '\\"')

    script = f'''
    tell application "Contacts"
        set matchedPeople to (every person whose value of every phone contains "{phone}")
        if (count of matchedPeople) > 0 then
            set thePerson to item 1 of matchedPeople
            set first name of thePerson to "{first_name}"
            set last name of thePerson to "{last_name}"
            save
        else
            set newPerson to make new person with properties {{first name:"{first_name}", last name:"{last_name}"}}
            make new phone at end of phones of newPerson with properties {{label:"mobile", value:"{phone}"}}
            save
        end if
    end tell
    '''

    try:
        subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=10
        )
    except Exception:
        pass
