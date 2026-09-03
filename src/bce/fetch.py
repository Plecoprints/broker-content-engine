"""Polite fetcher: robots.txt honoured, per-host rate limit (spec §10.2),
and every request address-validated against SSRF (`bce.netguard`).

Redirects are followed **manually**. `follow_redirects=True` handed the
decision to httpx, which meant a public hostname could redirect to an
internal address with no further check -- the compounding half of the SSRF
finding in the 2026-09-02 risk assessment. Following by hand costs a loop and
buys a validation point on every hop.
"""
import os
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx

from bce.netguard import MAX_REDIRECTS, BlockedAddressError, assert_fetchable

CONTACT_URL = os.environ.get("BCE_CONTACT_URL", "https://www.sunreef-yachts.com/")
USER_AGENT = f"SunreefPartnerContentBot/0.1 (+{CONTACT_URL})"


class Fetcher:
    def __init__(self, min_delay: float = 2.0, client: httpx.Client | None = None):
        self.min_delay = min_delay
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=False
        )
        # Forced, not merely defaulted, and on injected clients too. A client
        # that follows redirects internally never shows `_follow` the hops, so
        # every intermediate address goes unvalidated and the SSRF control is
        # silently off while looking present. The existing redirect test
        # injected exactly such a client and proved the point. A security
        # control that a caller can disable by accident is not a control.
        self._client.follow_redirects = False
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
        # `check_robots=False`, and it must be: robots.txt is the file that
        # decides what robots.txt permits, so consulting it here would recurse.
        # Address validation still applies -- this is an outbound request like
        # any other. Redirects are followed because http->https on /robots.txt
        # is ordinary, and refusing to follow would silently degrade every such
        # site to "no robots.txt found", i.e. allow-all, which is the wrong
        # direction to fail for a politeness control.
        response = self._follow(urljoin(url, "/robots.txt"), check_robots=False)
        if response is None or response.status_code != 200:
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

    def _follow(self, url: str, *, check_robots: bool) -> httpx.Response | None:
        """Request `url`, following redirects by hand and validating each hop.

        Returns the first non-redirect response, or None if any hop is
        refused -- blocked address, disallowed by robots, unfetchable scheme,
        transport error, or more than `MAX_REDIRECTS` hops. None is the single
        "we did not get this page" signal the callers already handle; the
        reason is deliberately not surfaced to them, because every reason has
        the same consequence and a partial fetch must never look like a page.
        """
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                assert_fetchable(current)
            except BlockedAddressError:
                return None
            if check_robots and not self.robots_allows(current):
                return None
            self._throttle(urlparse(current).netloc)
            try:
                response = self._client.get(current)
            except (httpx.HTTPError, httpx.InvalidURL, ValueError):
                return None
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            return response
        return None

    def get(self, url: str) -> str | None:
        response = self._follow(url, check_robots=True)
        if response is None or response.status_code != 200:
            return None
        return response.text
