"""SSRF defence for every outbound fetch (IT risk assessment 2026-09-02, §4).

**The finding.** `discover.normalize_domain` validated hostname *shape* and
nothing else, so `127.0.0.1`, `10.0.0.5`, `192.168.1.1`,
`metadata.google.internal` and `169.254.169.254` -- the cloud instance
metadata endpoint, the classic credential-theft target -- all imported as
ordinary brokers and were then fetched by the process. `follow_redirects=True`
compounded it: a public hostname could redirect to an internal address with no
further check.

On the operator's laptop, reading a CSV they wrote themselves, this is close
to unexploitable. On any hosted deployment it is an internal network scanner,
which is why the assessment rates it Critical and why it blocks server
deployment rather than merely being untidy.

**Two layers, because either alone is bypassable.**

1. `reject_literal_address` at import. A broker's *domain* is a hostname; a
   literal IP in that column is never a legitimate brokerage and is refused
   with a reason the operator can read. This alone is not a control -- a
   hostname can resolve wherever its owner points it -- but it catches the
   obvious case at the earliest point and keeps the import report honest.
2. `assert_fetchable` before every request, including **every redirect hop**.
   This resolves the hostname and refuses if *any* returned address is
   non-global. Resolution-time checking is the layer that actually holds,
   because it is the address the socket will use, not the string a human
   typed.

**What this does not fix, stated rather than implied.** Between resolving a
name and connecting to it there is a window in which DNS can change --
classic rebinding. Closing it properly means connecting to the validated IP
with the Host header pinned, which breaks TLS verification unless carefully
handled and is not worth the complexity here. The assessment's own
recommendation 3 names the right belt-and-braces: outbound network
restrictions at the infrastructure layer. This module narrows the window to
near-zero for a bulk crawler; it does not claim to eliminate it.
"""
import ipaddress
import socket
from urllib.parse import urlparse

#: Only these are ever fetched. `file:`, `gopher:`, `ftp:` and friends are
#: SSRF primitives in their own right and no broker site needs them.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: How many redirect hops to follow. Each one is re-validated; the cap stops a
#: redirect loop from becoming an unbounded resolve-and-fetch loop.
MAX_REDIRECTS = 5


class BlockedAddressError(ValueError):
    """A URL resolved somewhere we refuse to send a request."""


def _classify(ip: ipaddress._BaseAddress) -> str | None:
    """Why this address is refused, or None if it is a normal public one.

    `is_global` is the single authority rather than a hand-written range list:
    it already excludes loopback, private, link-local, carrier-grade NAT,
    reserved, multicast and unspecified space, and it tracks the registries
    instead of drifting from them. The specific labels below exist so a
    rejection tells the operator *what* was refused -- "link-local
    (cloud metadata range)" is actionable in a way that "blocked" is not.
    """
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local (cloud metadata range)"
    if ip.is_private:
        return "private/internal"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_reserved:
        return "reserved"
    if not ip.is_global:
        return "non-global"
    return None


def literal_address(host: str) -> ipaddress._BaseAddress | None:
    """The host parsed as a literal IP, or None if it is a hostname."""
    candidate = (host or "").strip().strip("[]")
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def reject_literal_address(host: str) -> str | None:
    """Layer 1. A reason string if `host` is a literal IP, else None.

    Every literal address is refused here, public ones included: the `domain`
    column holds a brokerage's hostname, and an IP in it is either a mistake
    or an attempt. Narrowing this to non-public addresses would buy nothing
    and would invite the question of which public IPs are acceptable.
    """
    ip = literal_address(host)
    if ip is None:
        return None
    reason = _classify(ip) or "public"
    return f"literal IP address ({reason}); a broker domain must be a hostname"


def resolve(host: str) -> list[ipaddress._BaseAddress]:
    """Every address `host` resolves to. Raises `BlockedAddressError` if the
    name does not resolve at all -- an unresolvable host is not fetchable, and
    saying so here keeps the caller from treating a DNS failure as a network
    blip worth retrying."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError) as exc:
        raise BlockedAddressError(f"{host}: does not resolve ({exc})") from exc
    out: list[ipaddress._BaseAddress] = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not out:
        raise BlockedAddressError(f"{host}: resolved to no usable address")
    return out


def assert_fetchable(url: str, *, resolver=None) -> None:
    """Layer 2. Raise `BlockedAddressError` unless every resolved address for
    `url`'s host is a normal public one.

    **Every** address, not any: a hostname with one public and one loopback
    record must be refused, because which one the socket picks is not ours to
    decide.

    `resolver` is injectable so tests can exercise the decision without
    touching DNS. It defaults to None and binds to the module-level `resolve`
    *at call time*, not as a default argument. A default binds once at
    definition, which silently defeats monkeypatching -- and did: two redirect
    tests passed because their hostnames failed DNS before the guard ran, not
    because the guard worked.
    """
    resolver = resolver or resolve
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedAddressError(
            f"{url}: scheme {parsed.scheme!r} is not fetchable "
            f"(allowed: {', '.join(sorted(ALLOWED_SCHEMES))})"
        )
    host = parsed.hostname
    if not host:
        raise BlockedAddressError(f"{url}: no host")

    literal = literal_address(host)
    addresses = [literal] if literal is not None else resolver(host)
    for ip in addresses:
        reason = _classify(ip)
        if reason is not None:
            raise BlockedAddressError(f"{url}: resolves to {ip} ({reason})")
