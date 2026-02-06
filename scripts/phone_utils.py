"""
Phone number utilities for normalization, extraction, and formatting.
"""

import re
import phonenumbers
from typing import Optional


def normalize_phone(phone: str, default_region: str = 'US') -> str:
    """
    Normalize phone number to E.164 format.

    Examples:
        - (555) 123-4567 → +15551234567
        - +1-555-123-4567 → +15551234567
        - 5551234567 → +15551234567 (assumes US)

    Args:
        phone: Phone number in any format
        default_region: Default region code (ISO 3166-1 alpha-2)

    Returns:
        Phone number in E.164 format

    Raises:
        ValueError: If phone number is invalid
    """
    try:
        parsed = phonenumbers.parse(phone, default_region)
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"Invalid phone number: {phone}")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException as e:
        raise ValueError(f"Cannot parse phone number '{phone}': {e}")


def extract_phone_from_text(text: str, default_region: str = 'US') -> Optional[str]:
    """
    Extract phone number from free text.

    Handles formats like:
        - +1 555-123-4567
        - (555) 123-4567
        - 5551234567
        - Call me at 555-123-4567

    Args:
        text: Text containing a phone number
        default_region: Default region code

    Returns:
        Phone number in E.164 format, or None if not found
    """
    try:
        # Use phonenumbers library's PhoneNumberMatcher
        for match in phonenumbers.PhoneNumberMatcher(text, default_region):
            phone = phonenumbers.format_number(
                match.number,
                phonenumbers.PhoneNumberFormat.E164
            )
            return phone
    except Exception:
        pass

    return None


def mask_phone(phone: str) -> str:
    """
    Partially mask phone number for privacy.

    Examples:
        - +15551234567 → +1555***4567
        - +447700900123 → +4477***0123

    Args:
        phone: Phone number in E.164 format

    Returns:
        Masked phone number
    """
    if len(phone) > 7:
        # Keep country code + first few digits, mask middle, show last 4
        visible_prefix_len = min(5, len(phone) - 4)
        return f"{phone[:visible_prefix_len]}***{phone[-4:]}"
    return phone


def format_phone_display(phone: str, default_region: str = 'US') -> str:
    """
    Format phone number for display (human-readable).

    Examples:
        - +15551234567 → (555) 123-4567
        - +447700900123 → +44 7700 900123

    Args:
        phone: Phone number in E.164 format
        default_region: Default region code

    Returns:
        Formatted phone number for display
    """
    try:
        parsed = phonenumbers.parse(phone, None)

        # If it's the default region, use NATIONAL format (cleaner)
        region = phonenumbers.region_code_for_number(parsed)
        if region == default_region:
            return phonenumbers.format_number(
                parsed,
                phonenumbers.PhoneNumberFormat.NATIONAL
            )
        else:
            # International format for other regions
            return phonenumbers.format_number(
                parsed,
                phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
    except Exception:
        return phone  # Return as-is if formatting fails


def is_valid_phone(phone: str, default_region: str = 'US') -> bool:
    """
    Check if a phone number is valid.

    Args:
        phone: Phone number in any format
        default_region: Default region code

    Returns:
        True if valid, False otherwise
    """
    try:
        parsed = phonenumbers.parse(phone, default_region)
        return phonenumbers.is_valid_number(parsed)
    except Exception:
        return False
