"""
Mock iMessage interface for testing without sending real messages.
"""

from typing import List, Dict, Optional
from collections import deque
import time


class MockIMSG:
    """
    Mock iMessage interface that simulates sending and receiving messages.

    Usage:
        imsg = MockIMSG()
        imsg.send("+15551234567", "Hello!")
        response = imsg.receive("+15551234567")
    """

    def __init__(self):
        self.sent_messages: List[Dict[str, any]] = []
        self.inbox: Dict[str, deque] = {}  # phone -> queue of messages
        self.bot_phone = "+15550000000"  # Mock bot phone number

    def send(self, to: str, text: str, from_phone: Optional[str] = None) -> None:
        """
        Send a message.

        Args:
            to: Recipient phone number
            text: Message text
            from_phone: Sender phone (defaults to bot phone)
        """
        message = {
            'from': from_phone or self.bot_phone,
            'to': to,
            'text': text,
            'timestamp': time.time()
        }
        self.sent_messages.append(message)
        print(f"[MOCK SEND] {message['from']} → {to}: {text}")

    def receive(self, from_phone: str, text: str) -> None:
        """
        Simulate receiving a message (for testing).

        Args:
            from_phone: Sender phone number
            text: Message text
        """
        if self.bot_phone not in self.inbox:
            self.inbox[self.bot_phone] = deque()

        message = {
            'from': from_phone,
            'to': self.bot_phone,
            'text': text,
            'timestamp': time.time()
        }
        self.inbox[self.bot_phone].append(message)
        print(f"[MOCK RECEIVE] {from_phone} → bot: {text}")

    def get_sent_messages(self, to: Optional[str] = None) -> List[Dict[str, any]]:
        """
        Get sent messages, optionally filtered by recipient.

        Args:
            to: Filter by recipient phone number

        Returns:
            List of sent messages
        """
        if to:
            return [msg for msg in self.sent_messages if msg['to'] == to]
        return self.sent_messages

    def get_last_sent_message(self, to: Optional[str] = None) -> Optional[Dict[str, any]]:
        """
        Get the last sent message, optionally filtered by recipient.

        Args:
            to: Filter by recipient phone number

        Returns:
            Last sent message or None
        """
        messages = self.get_sent_messages(to)
        return messages[-1] if messages else None

    def clear(self) -> None:
        """Clear all messages."""
        self.sent_messages.clear()
        self.inbox.clear()

    def get_conversation(self, phone: str) -> List[Dict[str, any]]:
        """
        Get all messages in a conversation (sent + received).

        Args:
            phone: Phone number of the conversation partner

        Returns:
            List of messages sorted by timestamp
        """
        sent = [msg for msg in self.sent_messages if msg['to'] == phone]
        received = []
        if self.bot_phone in self.inbox:
            received = [msg for msg in self.inbox[self.bot_phone] if msg['from'] == phone]

        all_messages = sent + received
        all_messages.sort(key=lambda m: m['timestamp'])
        return all_messages

    def assert_sent(self, to: str, text_contains: str) -> None:
        """
        Assert that a message was sent containing specific text.

        Args:
            to: Expected recipient
            text_contains: Text that should be in the message

        Raises:
            AssertionError: If no matching message found
        """
        messages = self.get_sent_messages(to)
        for msg in messages:
            if text_contains.lower() in msg['text'].lower():
                return

        raise AssertionError(
            f"No message sent to {to} containing '{text_contains}'\n"
            f"Sent messages: {[msg['text'] for msg in messages]}"
        )

    def assert_sent_count(self, to: str, expected_count: int) -> None:
        """
        Assert that a specific number of messages were sent to a recipient.

        Args:
            to: Expected recipient
            expected_count: Expected number of messages

        Raises:
            AssertionError: If count doesn't match
        """
        messages = self.get_sent_messages(to)
        actual_count = len(messages)
        if actual_count != expected_count:
            raise AssertionError(
                f"Expected {expected_count} messages to {to}, but got {actual_count}\n"
                f"Sent messages: {[msg['text'] for msg in messages]}"
            )


# Global mock instance for testing
mock_imsg = MockIMSG()
