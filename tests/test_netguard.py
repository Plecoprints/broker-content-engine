"""SSRF defence (IT risk assessment 2026-09-02, finding 1 — Critical).

The finding was that hostname validation checked shape and nothing else, so
loopback, private and cloud-metadata addresses imported as ordinary brokers
and were then fetched by the process, with `follow_redirects=True` able to
walk a public hostname to an internal one unchecked.

These tests cover both layers and, as importantly, that the guard does not
refuse ordinary broker sites — a control that blocks real work gets switched
off, and then it protects nothing.
"""
import ipaddress

import httpx
import pytest

from bce import netguard
from bce.discover import normalize_domain
from bce.fetch import Fetcher


def _stub(table):
    def resolver(host):
        return [ipaddress.ip_address(a) for a in table[host]]
    return resolver


# --- layer 1: literal addresses refused at import ------------------------

@pytest.mark.parametrize("address", [
    "127.0.0.1",            # loopback
    "169.254.169.254",      # cloud instance metadata — the credential target
    "10.0.0.5",             # RFC1918
    "192.168.1.1",
    "172.16.0.1",
    "0.0.0.0",
    "::1",
    "fd00::1",              # unique local
    "8.8.8.8",              # public, and still not a brokerage hostname
])
def test_a_literal_address_never_imports_as_a_broker(address):
    assert normalize_domain(address) is None
    assert netguard.reject_literal_address(address) is not None


@pytest.mark.parametrize("domain", [
    "acme-yachts.com", "www.acme-yachts.com", "https://acme-yachts.com/",
    "sunreef-yachts.com", "a-broker.co.uk",
])
def test_ordinary_broker_domains_still_import(domain):
    assert normalize_domain(domain) is not None


# --- layer 2: resolution-time validation ---------------------------------

@pytest.mark.parametrize("addresses,fragment", [
    (["127.0.0.1"], "loopback"),
    (["169.254.169.254"], "link-local"),
    (["10.0.0.5"], "private"),
    (["192.168.1.1"], "private"),
    (["::1"], "loopback"),
    (["224.0.0.1"], "multicast"),
])
def test_a_hostname_resolving_somewhere_internal_is_refused(addresses, fragment):
    """The layer that actually holds: the string is a perfectly ordinary
    hostname, and only resolution reveals where it points."""
    with pytest.raises(netguard.BlockedAddressError) as exc:
        netguard.assert_fetchable(
            "https://looks-fine.example/", resolver=_stub({"looks-fine.example": addresses})
        )
    assert fragment in str(exc.value)


def test_one_bad_record_among_good_ones_refuses_the_host():
    """Every address, not any. Which record the socket picks is not ours to
    decide, so a split-horizon or poisoned answer must not be a coin flip."""
    with pytest.raises(netguard.BlockedAddressError):
        netguard.assert_fetchable(
            "https://mixed.example/",
            resolver=_stub({"mixed.example": ["93.184.216.34", "127.0.0.1"]}),
        )


def test_a_normal_public_host_is_allowed():
    netguard.assert_fetchable(
        "https://acme.example/", resolver=_stub({"acme.example": ["93.184.216.34"]})
    )


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "gopher://acme.example/", "ftp://acme.example/",
])
def test_only_http_and_https_are_fetchable(url):
    with pytest.raises(netguard.BlockedAddressError):
        netguard.assert_fetchable(url)


def test_an_unresolvable_host_is_refused_not_retried():
    with pytest.raises(netguard.BlockedAddressError):
        netguard.assert_fetchable("https://nx.invalid/")


# --- the fetcher: every hop, and no way to switch it off -----------------

def test_a_redirect_to_an_internal_address_is_not_followed(monkeypatch):
    """The compounding half of the finding. The first hop is a legitimate
    public site; the redirect target is internal."""
    monkeypatch.setattr(netguard, "resolve", _stub({
        "acme.example": ["93.184.216.34"],          # a real, public first hop
        "internal.example": ["169.254.169.254"],    # the metadata endpoint
    }))

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "acme.example":
            return httpx.Response(301, headers={"location": "https://internal.example/x"})
        return httpx.Response(200, text="SECRET")

    f = Fetcher(min_delay=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert f.get("https://acme.example/page") is None


def test_an_injected_redirect_following_client_cannot_disable_the_guard():
    """A client that follows redirects internally never shows the hops to the
    validator, so the control would be off while appearing present. `Fetcher`
    forces it off on whatever it is handed."""
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")),
        follow_redirects=True,
    )
    Fetcher(min_delay=0, client=client)
    assert client.follow_redirects is False


def test_redirect_chains_are_bounded(monkeypatch):
    """A redirect loop must not become an unbounded resolve-and-fetch loop."""
    monkeypatch.setattr(netguard, "resolve", _stub({"acme.example": ["93.184.216.34"]}))
    hops = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        hops["n"] += 1
        return httpx.Response(301, headers={"location": "https://acme.example/next"})

    f = Fetcher(min_delay=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert f.get("https://acme.example/start") is None
    # Non-vacuous in both directions: it really did follow (>1), and it really
    # did stop (<= the cap). An earlier version of this test asserted only the
    # upper bound and passed with zero hops, because the hostname failed DNS
    # before the redirect logic ran.
    assert 1 < hops["n"] <= netguard.MAX_REDIRECTS + 1
