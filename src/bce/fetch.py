"""Polite fetcher: robots.txt honoured, per-host rate limit (spec §10.2)."""
import os
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx

CONTACT_URL = os.environ.get("BCE_CONTACT_URL", "https://www.sunreef-yachts.com/")
USER_AGENT = f"SunreefPartnerContentBot/0.1 (+{CONTACT_URL})"


class Fetcher:
    def __init__(self, min_delay: float = 2.0, client: httpx.Client | None = None):
        self.min_delay = min_delay
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}

    def robots_allows(self, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self._robots:
            self._robots[host] = self._load_robots(url)
        parser = self._robots[host]
        if parser is None:
            return True
        return parser.can_fetch(USER_AGENT, url)

    def _load_robots(self, url: str):
        robots_url = urljoin(url, "/robots.txt")
        try:
            response = self._client.get(robots_url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        now = time.monotonic()
        if last is not None:
            elapsed = now - last
            if elapsed < self.min_delay:
                time.sleep(self.min_delay - elapsed)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str) -> str | None:
        if not self.robots_allows(url):
            return None
        self._throttle(urlparse(url).netloc)
        try:
            response = self._client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        return response.text
