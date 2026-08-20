import httpx
import pytest
from bce.fetch import Fetcher, USER_AGENT


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_user_agent_identifies_and_carries_contact_url():
    assert "SunreefPartnerContentBot" in USER_AGENT
    assert "http" in USER_AGENT


def test_robots_allows_when_permitted():
    def handler(request):
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.robots_allows("https://acme.com/blog") is True


def test_robots_blocks_disallowed_path():
    def handler(request):
        return httpx.Response(200, text="User-agent: *\nDisallow: /private")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.robots_allows("https://acme.com/private/x") is False


def test_missing_robots_is_treated_as_allowed():
    def handler(request):
        return httpx.Response(404)
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.robots_allows("https://acme.com/") is True


def test_get_returns_none_when_disallowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        return httpx.Response(200, text="body")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("https://acme.com/page") is None


def test_get_returns_body_when_allowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text="hello")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("https://acme.com/page") == "hello"


def test_get_returns_none_on_error_status():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(500)
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("https://acme.com/page") is None


def test_rate_limit_sleeps_between_same_host_requests(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("bce.fetch.time.sleep", lambda s: slept.append(s))
    monkeypatch.setattr("bce.fetch.time.monotonic", lambda: 0.0)

    def handler(request):
        return httpx.Response(200, text="ok")

    f = Fetcher(min_delay=2.0, client=_client(handler))
    f.get("https://acme.com/a")
    f.get("https://acme.com/b")
    assert any(s > 0 for s in slept)


def test_user_agent_sent_in_request_headers():
    captured_headers: dict = {}

    def handler(request):
        captured_headers.update(request.headers)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text="hello")

    f = Fetcher(
        min_delay=0,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": USER_AGENT},
        ),
    )
    f.get("https://acme.com/page")
    assert captured_headers.get("user-agent") == USER_AGENT


def test_get_returns_none_for_malformed_url():
    def handler(request):
        return httpx.Response(200, text="ok")

    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("not a valid url at all") is None


def test_get_returns_none_if_redirect_target_disallowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        if request.url.path == "/page":
            # Redirect to a disallowed path
            return httpx.Response(301, headers={"location": "https://acme.com/private/target"})
        return httpx.Response(200, text="target content")

    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("https://acme.com/page") is None
