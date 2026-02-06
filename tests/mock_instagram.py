"""
Mock Instagram browser for testing.
Configurable with fake following data for test scenarios.
"""


class MockInstagramBrowser:
    """
    Mock replacement for InstagramBrowser.
    Pre-load following_data to simulate scrape results.
    """

    def __init__(self):
        # handle -> list of handles they follow
        self.following_data = {}
        # handle -> 'followed' | 'requested' | 'not_found' etc.
        self.follow_results = {}
        # Track calls
        self.follow_calls = []
        self.scrape_calls = []

    def set_following(self, handle: str, follows: list):
        """Set fake following list for a handle."""
        self.following_data[handle.lower()] = [h.lower() for h in follows]

    def set_follow_result(self, handle: str, result: str):
        """Set what follow_user returns for a handle."""
        self.follow_results[handle.lower()] = result

    def follow_user(self, handle: str) -> str:
        handle = handle.lower()
        self.follow_calls.append(handle)
        return self.follow_results.get(handle, 'followed')

    def scrape_following(self, handle: str):
        handle = handle.lower()
        self.scrape_calls.append(handle)
        if handle in self.following_data:
            return self.following_data[handle]
        return None  # Simulate private / inaccessible

    def close(self):
        pass
