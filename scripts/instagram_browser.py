"""
Instagram browser controller using Playwright.
Manages a Chromium session logged into @yed.flowers for following guests
and scraping their following lists.
"""

import json
import os
import time
import random
import logging

logger = logging.getLogger(__name__)

SESSION_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'ig_session.json')
MIN_NAV_DELAY = 3
FOLLOW_SCRAPE_DELAY = 5
JITTER_RANGE = (1, 3)


class InstagramBrowser:
    """Playwright-based Instagram browser controller. Singleton pattern."""

    _instance = None

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._last_nav_time = 0

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _is_testing(self):
        return bool(os.environ.get('FLOWERS_TESTING'))

    def _wait_rate_limit(self):
        """Enforce minimum delay between navigations."""
        elapsed = time.time() - self._last_nav_time
        if elapsed < MIN_NAV_DELAY:
            time.sleep(MIN_NAV_DELAY - elapsed + random.uniform(*JITTER_RANGE))
        self._last_nav_time = time.time()

    def _ensure_browser(self):
        """Launch browser if not already running, loading saved session."""
        if self._page is not None:
            return

        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)

        if os.path.exists(SESSION_PATH):
            self._context = self._browser.new_context(storage_state=SESSION_PATH)
        else:
            self._context = self._browser.new_context()

        self._page = self._context.new_page()

    def _is_logged_in(self) -> bool:
        """Check if current session is authenticated."""
        try:
            url = self._page.url
            return 'login' not in url and 'accounts' not in url
        except Exception:
            return False

    def _save_session(self):
        """Save browser cookies/storage to disk."""
        try:
            os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
            self._context.storage_state(path=SESSION_PATH)
        except Exception as e:
            logger.warning(f"Failed to save IG session: {e}")

    def login_interactive(self):
        """Open a visible browser for one-time manual login."""
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://www.instagram.com/accounts/login/")
        print("Log in to Instagram in the browser window.")
        print("Press Enter here once you're logged in and see your feed...")
        input()

        os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
        context.storage_state(path=SESSION_PATH)
        print(f"Session saved to {SESSION_PATH}")

        browser.close()
        pw.stop()

    def follow_user(self, handle: str) -> str:
        """
        Follow a user on Instagram.

        Returns: 'followed', 'requested', 'already_following', 'not_found', or 'error'
        """
        if self._is_testing():
            return 'followed'

        try:
            self._ensure_browser()
            self._wait_rate_limit()

            self._page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded")
            time.sleep(2)

            if not self._is_logged_in():
                logger.warning("IG session expired — redirected to login")
                return 'error'

            # Check if page exists
            if self._page.query_selector('text="Sorry, this page isn\'t available."'):
                return 'not_found'

            # Check if already following
            following_btn = self._page.query_selector('button:has-text("Following")')
            requested_btn = self._page.query_selector('button:has-text("Requested")')
            if following_btn:
                return 'already_following'
            if requested_btn:
                return 'requested'

            # Click Follow
            follow_btn = self._page.query_selector('button:has-text("Follow")')
            if not follow_btn:
                return 'error'

            follow_btn.click()
            time.sleep(2)

            # Check result
            if self._page.query_selector('button:has-text("Requested")'):
                self._save_session()
                return 'requested'
            if self._page.query_selector('button:has-text("Following")'):
                self._save_session()
                return 'followed'

            return 'error'

        except Exception as e:
            logger.error(f"Error following {handle}: {e}")
            return 'error'

    def scrape_following(self, handle: str) -> list:
        """
        Scrape a user's following list.

        Returns list of handles they follow, or None if private/inaccessible.
        """
        if self._is_testing():
            return []

        try:
            self._ensure_browser()
            self._wait_rate_limit()

            self._page.goto(f"https://www.instagram.com/{handle}/", wait_until="domcontentloaded")
            time.sleep(2)

            if not self._is_logged_in():
                logger.warning("IG session expired — redirected to login")
                return None

            # Check if page exists
            if self._page.query_selector('text="Sorry, this page isn\'t available."'):
                return None

            # Check if private
            if self._page.query_selector('text="This account is private"'):
                return None

            # Click "following" link
            following_link = self._page.query_selector(f'a[href="/{handle}/following/"]')
            if not following_link:
                return None

            following_link.click()
            time.sleep(3)

            # Use in-browser JS to scroll and collect handles.
            # This avoids Playwright element handle GC issues on large lists.
            result = self._page.evaluate('''async () => {
                const delay = ms => new Promise(r => setTimeout(r, ms));

                const dialog = document.querySelector('div[role="dialog"]');
                if (!dialog) return { error: 'no dialog' };

                let scrollable = null;
                const divs = dialog.querySelectorAll('div');
                for (const d of divs) {
                    const style = window.getComputedStyle(d);
                    if ((style.overflowY === 'scroll' || style.overflowY === 'auto')
                        && d.scrollHeight > d.clientHeight) {
                        scrollable = d;
                        break;
                    }
                }
                if (!scrollable) return { error: 'no scrollable' };

                const handles = new Set();
                let prevCount = 0;
                let stallCount = 0;

                for (let i = 0; i < 800; i++) {
                    const links = dialog.querySelectorAll('a[role="link"]');
                    for (const link of links) {
                        const href = link.getAttribute('href');
                        if (href && href.startsWith('/')
                            && (href.match(/\\//g) || []).length === 2) {
                            const h = href.replace(/\\//g, '').toLowerCase();
                            if (h && !['explore','reels','direct','accounts'].includes(h)) {
                                handles.add(h);
                            }
                        }
                    }

                    if (handles.size === prevCount) {
                        stallCount++;
                        if (stallCount >= 10) break;
                    } else {
                        stallCount = 0;
                    }
                    prevCount = handles.size;

                    scrollable.scrollTop = scrollable.scrollHeight;
                    await delay(600 + Math.random() * 800);
                }

                return { handles: Array.from(handles), count: handles.size };
            }''')

            self._save_session()

            if isinstance(result, dict) and 'error' in result:
                logger.warning(f"Scrape dialog error: {result['error']}")
                return None

            return result.get('handles', [])

        except Exception as e:
            logger.error(f"Error scraping following for {handle}: {e}")
            return None

    def close(self):
        """Shut down browser."""
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        InstagramBrowser._instance = None


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'login':
        browser = InstagramBrowser()
        browser.login_interactive()
    else:
        print("Usage: python3 instagram_browser.py login")
