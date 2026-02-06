"""
Unit tests for phone_utils module.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest
from phone_utils import (
    normalize_phone,
    extract_phone_from_text,
    mask_phone,
    format_phone_display,
    is_valid_phone
)


class TestNormalizePhone:
    """Tests for normalize_phone function."""

    def test_normalize_us_formats(self):
        """Test various US phone number formats."""
        expected = "+12025551234"

        assert normalize_phone("(202) 555-1234") == expected
        assert normalize_phone("202-555-1234") == expected
        assert normalize_phone("2025551234") == expected
        assert normalize_phone("+1-202-555-1234") == expected
        assert normalize_phone("+12025551234") == expected
        assert normalize_phone("1-202-555-1234") == expected

    def test_normalize_with_spaces(self):
        """Test phone numbers with spaces."""
        expected = "+12025551234"
        assert normalize_phone("+1 202 555 1234") == expected
        assert normalize_phone("202 555 1234") == expected

    def test_normalize_international(self):
        """Test international phone numbers."""
        assert normalize_phone("+44 20 7946 0958") == "+442079460958"
        assert normalize_phone("+33 1 23 45 67 89") == "+33123456789"

    def test_invalid_phone(self):
        """Test invalid phone numbers raise ValueError."""
        with pytest.raises(ValueError):
            normalize_phone("123")  # Too short

        with pytest.raises(ValueError):
            normalize_phone("abc-def-ghij")  # Not a number

        with pytest.raises(ValueError):
            normalize_phone("")  # Empty


class TestExtractPhoneFromText:
    """Tests for extract_phone_from_text function."""

    def test_extract_from_simple_text(self):
        """Test extracting phone from simple text."""
        assert extract_phone_from_text("My number is (202) 555-1234") == "+12025551234"
        assert extract_phone_from_text("Call me at 202-555-1234") == "+12025551234"
        assert extract_phone_from_text("2025551234") == "+12025551234"

    def test_extract_from_complex_text(self):
        """Test extracting phone from complex text."""
        text = "Hey, can you call me at (202) 555-1234 tomorrow?"
        assert extract_phone_from_text(text) == "+12025551234"

    def test_extract_no_phone(self):
        """Test extracting from text with no phone number."""
        assert extract_phone_from_text("No phone number here") is None
        assert extract_phone_from_text("123 is not a phone") is None

    def test_extract_multiple_phones(self):
        """Test extracting when multiple phones present (returns first)."""
        text = "Call (202) 555-1234 or (202) 555-6789"
        result = extract_phone_from_text(text)
        assert result in ["+12025551234", "+12025556789"]


class TestMaskPhone:
    """Tests for mask_phone function."""

    def test_mask_us_phone(self):
        """Test masking US phone numbers."""
        assert mask_phone("+12025551234") == "+1202***1234"

    def test_mask_international(self):
        """Test masking international phone numbers."""
        assert mask_phone("+447700900123") == "+4477***0123"

    def test_mask_short_phone(self):
        """Test masking short phone numbers."""
        result = mask_phone("+1234")
        assert result == "+1234"  # Too short to mask properly


class TestFormatPhoneDisplay:
    """Tests for format_phone_display function."""

    def test_format_us_national(self):
        """Test formatting US numbers in national format."""
        result = format_phone_display("+12025551234")
        assert "202" in result
        assert "1234" in result

    def test_format_international(self):
        """Test formatting international numbers."""
        result = format_phone_display("+447700900123")
        assert "+44" in result


class TestIsValidPhone:
    """Tests for is_valid_phone function."""

    def test_valid_phones(self):
        """Test valid phone numbers."""
        assert is_valid_phone("+12025551234") is True
        assert is_valid_phone("(202) 555-1234") is True
        assert is_valid_phone("2025551234") is True

    def test_invalid_phones(self):
        """Test invalid phone numbers."""
        assert is_valid_phone("123") is False
        assert is_valid_phone("abc") is False
        assert is_valid_phone("") is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
