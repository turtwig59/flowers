"""
Contact card (vCard) parsing utilities.
"""

import re
from typing import Optional, Dict
from phone_utils import normalize_phone


def parse_vcard(vcard_content: str) -> Dict[str, Optional[str]]:
    """
    Parse vCard content and extract name and phone number.

    Handles both vCard 3.0 and 4.0 formats.

    Args:
        vcard_content: vCard file content as string

    Returns:
        dict with keys: name, phone, email
        phone is normalized to E.164 format
    """
    result = {
        'name': None,
        'phone': None,
        'email': None
    }

    lines = vcard_content.strip().split('\n')

    for line in lines:
        line = line.strip()

        # Extract name (FN field)
        if line.startswith('FN:'):
            result['name'] = line[3:].strip()

        # Extract phone (TEL field)
        # Prioritize mobile/cell numbers
        elif line.startswith('TEL') or line.startswith('tel'):
            # Extract phone number from various formats:
            # TEL;TYPE=CELL:+15551234567
            # TEL;CELL:+15551234567
            # TEL:+15551234567
            # tel:+15551234567

            # Check if it's a mobile/cell number
            is_mobile = 'CELL' in line.upper() or 'MOBILE' in line.upper()

            # Extract the phone number (after the colon)
            parts = line.split(':', 1)
            if len(parts) == 2:
                phone_raw = parts[1].strip()
                try:
                    normalized = normalize_phone(phone_raw)
                    # If we already have a phone and this is mobile, replace it
                    # Otherwise, only set if we don't have one yet
                    if is_mobile or result['phone'] is None:
                        result['phone'] = normalized
                except ValueError:
                    # Invalid phone, skip
                    pass

        # Extract email (EMAIL field)
        elif line.startswith('EMAIL'):
            parts = line.split(':', 1)
            if len(parts) == 2:
                result['email'] = parts[1].strip()

    return result


def parse_vcard_file(vcard_path: str) -> Dict[str, Optional[str]]:
    """
    Parse vCard file and extract name and phone number.

    Args:
        vcard_path: Path to vCard file

    Returns:
        dict with keys: name, phone, email
    """
    with open(vcard_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return parse_vcard(content)


def extract_name_from_text(text: str) -> Optional[str]:
    """
    Extract a name from free text.

    Simple heuristic: assume the text is a name if it's:
    - 1-4 words
    - Each word starts with capital letter
    - No numbers or special characters (except spaces, hyphens, apostrophes)

    Args:
        text: Text that might be a name

    Returns:
        Cleaned name or None if it doesn't look like a name
    """
    text = text.strip()

    # Remove common prefixes/suffixes
    text = re.sub(r'^(hi|hey|hello|this is|i\'m|my name is)\s+', '', text, flags=re.IGNORECASE)
    text = text.strip()

    # Check if it looks like a name
    # Allow letters, spaces, hyphens, apostrophes, and accented characters
    if not re.match(r'^[\w\s\'-]+$', text, re.UNICODE):
        return None

    # Split into words
    words = text.split()

    # Name should be 1-4 words
    if len(words) < 1 or len(words) > 4:
        return None

    # Each word should be at least 2 characters (except middle initials)
    for word in words:
        if len(word) == 1 and word.upper() != word:
            # Single letter but not capitalized (not an initial)
            return None

    # Looks good, return capitalized version
    return ' '.join(word.capitalize() for word in words)
