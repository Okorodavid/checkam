"""Is the link itself dangerous? Public phishing/malware blocklists plus link tricks scammers use.

Blocklists (`python -m checkam refresh` downloads them; free, no key):
  - OpenPhish community feed: live phishing URLs.
  - Phishing Army: ~100k known phishing domains.
Optional, with free keys: Google Safe Browsing, URLhaus (abuse.ch).
"""

from __future__ import annotations

import ipaddress
import re
import time

import httpx

from ..evidence import CAUTION, FREE_HOSTS, SCAM, Entities, Evidence, host_of, registrable_domain
from ..store import Store
from .official import owner_of, registry

SOURCE = "Link safety check"
FEEDS = {
    "OpenPhish": ("https://openphish.com/feed.txt", "url", "https://openphish.com/"),
    "Phishing Army": ("https://phishing.army/download/phishing_army_blocklist.txt", "host", "https://phishing.army/"),
}
SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "rb.gy", "is.gd", "shorturl.at", "tiny.cc", "ow.ly", "rebrand.ly",
              "s.id", "t.ly", "t.co", "goo.gl", "bitly.com", "shorte.st", "v.gd", "qr.ae", "lnkd.in", "wa.link", "tr.ee"}
RISKY_TLDS = {"xyz", "top", "icu", "click", "sbs", "cfd", "buzz", "rest", "monster", "cyou", "lol", "bond", "zip", "mov",
              "gq", "ml", "tk", "cf", "ga", "work", "support", "live", "vip"}
APP_FILE = re.compile(r"(?i)\.(apk|xapk|exe|scr|bat|msi|jar)(\?|$)")


def is_shortener(host: str) -> bool:
    return host in SHORTENERS or registrable_domain(host) in SHORTENERS


def tricks(url: str) -> list[Evidence]:
    """Offline red flags in how the link is built."""
    out: list[Evidence] = []
    raw = re.sub(r"(?i)^https?://", "", url)
    authority = raw.split("/")[0]
    host = host_of(url)
    if "@" in authority:
        out.append(Evidence(SOURCE, "The link hides its real address behind an '@' sign, a trick to make it look like another site.", SCAM, 2))
    try:
        ipaddress.ip_address(host)
        out.append(Evidence(SOURCE, f"The link goes to a bare number address ({host}) instead of a company name. Real companies don't do that.", SCAM, 2))
    except ValueError:
        pass
    if "xn--" in host:
        out.append(Evidence(SOURCE, f"The link uses look-alike letters ({host}) so it can pass for a real site.", SCAM, 2))
    if APP_FILE.search(raw.split("?")[0] + "?"):
        out.append(Evidence(SOURCE, "The link downloads an app file directly, outside the Play Store. Fake bank and loan apps spread this way and can read your SMS codes.",
                            SCAM, 3))
    if is_shortener(host):
        out.append(Evidence(SOURCE, f"It's a short link ({host}), which hides where it really goes.", CAUTION, 1))
    free = next((f for f in FREE_HOSTS if host.endswith("." + f)), None)
    if free:
        out.append(Evidence(SOURCE, f"The page is on {free}, a free website host where anyone can make a page in minutes. Real banks and agencies use their own websites.",
                            CAUTION, 2))
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    if tld in RISKY_TLDS and not owner_of(registrable_domain(host)):
        out.append(Evidence(SOURCE, f"The site ends in .{tld}, a cheap web address that scammers use a lot.", CAUTION, 1))
    reg = registrable_domain(host)
    sub = host[: -len(reg)].rstrip(".") if host.endswith(reg) else ""
    if sub and not owner_of(reg):
        for o in registry():
            if any(len(a.replace(" ", "")) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(a.replace(' ', ''))}(?![a-z0-9])", sub) for a in o.aliases):
                out.append(Evidence(SOURCE, f"The link puts \"{o.name}\" in front of a different site ({reg}) to look official. {o.name}'s real site is {o.site()}.",
                                    SCAM, 3, f"https://{o.site()}"))
                break
    return out


def blocklisted(url: str, store: Store) -> list[Evidence]:
    host = host_of(url)
    full = url if url.lower().startswith("http") else "https://" + url
    hits = set(store.threat_hits(host, full)) | set(store.threat_hits(host, "http://" + re.sub(r"(?i)^https?://", "", full)))
    reg = registrable_domain(host)
    if reg != host:
        hits |= {s for s in store.threat_hits(reg, "") }
    out = []
    for source in sorted(hits):
        updated = store.threat_updated(source)
        when = time.strftime("%d %b %Y", time.gmtime(updated)) if updated else "recently"
        out.append(Evidence(source, f"{host} is on the {source} list of known phishing or malware sites (list updated {when}).",
                            SCAM, 4, FEEDS.get(source, ("", "", ""))[2]))
    return out


async def safe_browsing(urls: list[str], api_key: str, client: httpx.AsyncClient) -> list[Evidence]:
    if not api_key or not urls:
        return []
    body = {
        "client": {"clientId": "checkam", "clientVersion": "0.1"},
        "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
                       "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                       "threatEntries": [{"url": u if u.startswith("http") else "https://" + u} for u in urls]},
    }
    try:
        r = await client.post(f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={api_key}", json=body, timeout=10)
    except httpx.HTTPError:
        return []
    if r.status_code != 200:
        return []
    out = []
    for m in r.json().get("matches", []):
        kind = m.get("threatType", "").replace("_", " ").lower()
        out.append(Evidence("Google Safe Browsing", f"Google Safe Browsing flags {host_of(m['threat']['url'])} as {kind}.", SCAM, 4,
                            "https://transparencyreport.google.com/safe-browsing/search"))
    return out


async def urlhaus(urls: list[str], auth_key: str, client: httpx.AsyncClient) -> list[Evidence]:
    out = []
    for u in urls[:2] if auth_key else []:
        try:
            r = await client.post("https://urlhaus-api.abuse.ch/v1/url/", data={"url": u}, headers={"Auth-Key": auth_key}, timeout=10)
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and r.json().get("query_status") == "ok":
            out.append(Evidence("URLhaus", f"{host_of(u)} is listed by URLhaus as a malware download site.", SCAM, 4, r.json().get("urlhaus_reference", "")))
    return out


def check(ents: Entities, store: Store) -> list[Evidence]:
    out: list[Evidence] = []
    seen: set[str] = set()
    for url in ents.urls[:4]:
        for e in tricks(url) + blocklisted(url, store):
            if e.finding not in seen:
                seen.add(e.finding)
                out.append(e)
    return out


async def refresh(store: Store, client: httpx.AsyncClient) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, (url, kind, _) in FEEDS.items():
        try:
            r = await client.get(url, timeout=60, follow_redirects=True)
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        rows: list[tuple[str, str]] = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append((host_of(line), line) if kind == "url" else (line.lower(), ""))
        if rows:
            store.replace_threats(name, rows)
            counts[name] = len(rows)
    return counts
