"""Links in the message: how old is the website (public RDAP registry), and what does the page ask for?"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import date, datetime, timezone

import httpx

from ..evidence import CAUTION, FREE_HOSTS, INFO, SCAM, Entities, Evidence, host_of, registrable_domain
from ..store import Store
from .official import owner_of

RDAP = "Domain record (RDAP)"
PAGE = "The linked page"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) CheckAm/0.1 (+scam check)"}
MAX_PAGE_BYTES = 400_000
SECRET_FIELD = re.compile(r"(?i)<input[^>]+(type=[\"']?password|name=[\"']?[^\"'>]*(pin|otp|cvv|card|bvn|token)[^\"'>]*)")
TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")


def _age_text(created: date, today: date) -> tuple[str, int]:
    days = (today - created).days
    if days < 1:
        return "today", days
    if days < 60:
        return f"{days} day{'s' if days != 1 else ''} ago", days
    if days < 730:
        return f"about {days // 30} months ago", days
    return f"in {created.year}", days


async def domain_age(client: httpx.AsyncClient, store: Store, domain: str, today: date | None = None) -> Evidence | None:
    if owner_of(domain) or ".".join(domain.split(".")[-2:]) in FREE_HOSTS:
        return None  # a known real site, or a free host whose own age says nothing about this page
    today = today or datetime.now(timezone.utc).date()
    created = store.rdap_get(domain)
    if created is None:
        try:
            r = await client.get(f"https://rdap.org/domain/{domain}", timeout=12, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if r.status_code == 404:
            return Evidence(RDAP, f"{domain} has no public registration record I could find. It may be unregistered or hidden.", CAUTION, 1,
                            f"https://lookup.icann.org/en/lookup?name={domain}")
        if r.status_code != 200:
            return None  # rate-limited or the registry has no RDAP: say nothing rather than guess
        events = {e.get("eventAction"): e.get("eventDate", "") for e in r.json().get("events", [])}
        created = (events.get("registration") or "")[:10]
        store.rdap_put(domain, created)
    if not created:
        return None
    try:
        made = date.fromisoformat(created)
    except ValueError:
        return None
    when, days = _age_text(made, today)
    url = f"https://lookup.icann.org/en/lookup?name={domain}"
    if days < 30:
        return Evidence(RDAP, f"The website {domain} was created {when} ({made:%d %b %Y}). Scam sites are usually brand new.", SCAM, 3, url)
    if days < 180:
        return Evidence(RDAP, f"The website {domain} is new: created {when} ({made:%d %b %Y}).", CAUTION, 1, url)
    return Evidence(RDAP, f"The website {domain} was created {when}. Being old doesn't make it safe, but it isn't brand new.", INFO, 0, url)


def _public_host(host: str) -> bool:
    """Never let a message make the server fetch its own network (SSRF)."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


async def page(client: httpx.AsyncClient, url: str) -> list[Evidence]:
    if not url.lower().startswith("http"):
        url = "https://" + url
    host = host_of(url)
    if not await asyncio.to_thread(_public_host, host):
        return []
    try:
        async with client.stream("GET", url, timeout=10, follow_redirects=True, headers=UA) as r:
            body = b""
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > MAX_PAGE_BYTES:
                    break
            final = str(r.url)
    except httpx.HTTPError:
        return [Evidence(PAGE, f"The link {host} did not open when I tried it. Scam sites often go offline quickly.", INFO, 0)]
    html = body.decode("utf-8", "ignore")
    out: list[Evidence] = []
    final_dom = registrable_domain(host_of(final))
    if final_dom != registrable_domain(host):
        out.append(Evidence(PAGE, f"The link {host} quietly redirects to a different site, {final_dom}.", CAUTION, 2, final))
    if SECRET_FIELD.search(html):
        out.append(Evidence(PAGE, f"The page at {host_of(final)} has boxes asking for a PIN, password, OTP or card number.", SCAM, 3, final))
    title = TITLE.search(html)
    if title and not out:
        t = re.sub(r"\s+", " ", title.group(1)).strip()[:80]
        if t:
            out.append(Evidence(PAGE, f"The page's title is \"{t}\".", INFO, 0, final))
    return out


async def expand(client: httpx.AsyncClient, url: str) -> str | None:
    """Where a short link really goes, without downloading the destination page."""
    full = url if url.lower().startswith("http") else "https://" + url
    if not await asyncio.to_thread(_public_host, host_of(full)):
        return None
    current = full
    for _ in range(6):
        try:
            r = await client.head(current, timeout=8, follow_redirects=False, headers=UA)
        except httpx.HTTPError:
            return None
        loc = r.headers.get("location")
        if r.status_code in (301, 302, 303, 307, 308) and loc:
            current = str(httpx.URL(current).join(loc))
            continue
        break
    return current if host_of(current) != host_of(full) else None


async def check(ents: Entities, store: Store, client: httpx.AsyncClient) -> list[Evidence]:
    domains = ents.domains[:3]
    urls = [u for u in ents.urls if not owner_of(registrable_domain(host_of(u)))][:2]
    results = await asyncio.gather(*[domain_age(client, store, d) for d in domains], *[page(client, u) for u in urls],
                                   return_exceptions=True)
    out: list[Evidence] = []
    for r in results:
        if isinstance(r, Evidence):
            out.append(r)
        elif isinstance(r, list):
            out.extend(r)
    return out
