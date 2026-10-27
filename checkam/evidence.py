"""Evidence records and the things worth checking inside a message."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# What a finding says about the message.
SCAM, CAUTION, SAFE, INFO = "scam", "caution", "safe", "info"


@dataclass
class Evidence:
    source: str  # who says so: "Message check", "Domain record (RDAP)", "SEC Nigeria", ...
    finding: str  # one plain sentence a parent can read
    signal: str  # SCAM | CAUTION | SAFE | INFO
    weight: int = 1  # 0-3, how strongly it points that way
    url: str = ""  # where to see it yourself
    id: str = ""  # "E1", assigned once all sources are in


@dataclass
class Entities:
    text: str
    urls: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)  # 10-digit NUBAN account numbers
    handles: list[str] = field(default_factory=list)  # X / Telegram @handles, lower-case, no @
    names: list[str] = field(default_factory=list)  # company-like names worth looking up

    def lookups(self) -> list[tuple[str, str]]:
        """(kind, value) pairs remembered so repeat reports can be spotted."""
        return ([("account", a) for a in self.accounts] + [("phone", p) for p in self.phones]
                + [("domain", d) for d in self.domains] + [("handle", h) for h in self.handles])


URL_RE = re.compile(
    r"(?i)\b((?:https?://|www\.)[^\s<>\"']+|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{1,63})*"
    r"\.(?:com|ng|net|org|io|co|xyz|top|online|site|info|biz|app|shop|vip|club|live|link|me|cc|icu|pro|sbs|cfd|"
    r"buzz|click|rest|monster|cyou|lol|bond|store|tech|website|space|fun|gq|ml|tk|ly|gl|gd|at|to|ws|in|us|uk|dev)"
    r"(?:\.ng)?(?:/[^\s<>\"']*)?)"
)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?234[\s-]?|0)([789][01]\d)[\s-]?(\d{3})[\s-]?(\d{4})(?!\d)")
ACCOUNT_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
HANDLE_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_]{2,15})\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NAME_RE = re.compile(
    r"\b((?:[A-Z][\w&'-]*\s){0,3}(?:Global|Investment|Investments|Capital|Wealth|Fund|Funds|Coin|Cooperative|"
    r"Finance|Finances|Loan|Loans|Credit|Microfinance|Limited|Ltd|Ventures|Trade|Trading|Exchange|Farms|Empire))\b"
)
TWO_PART_TLDS = {"com.ng", "gov.ng", "org.ng", "edu.ng", "net.ng", "co.uk", "com.gh", "co.za"}
# Free hosts where anyone gets a subdomain: the subdomain is the real "site", not the host company.
FREE_HOSTS = {"eu.org", "vercel.app", "netlify.app", "github.io", "pages.dev", "web.app", "firebaseapp.com", "blogspot.com",
              "wixsite.com", "weebly.com", "000webhostapp.com", "ngrok.io", "ngrok-free.app", "glitch.me", "replit.app",
              "onrender.com", "herokuapp.com", "workers.dev", "framer.website", "webflow.io", "carrd.co", "sites.google.com",
              "godaddysites.com", "mystrikingly.com", "square.site", "wordpress.com", "r2.dev", "surge.sh"}


# Country domains usually sell names under these: roblox.com.et, gov.za, ac.ke.
SECOND_LEVEL = {"com", "net", "org", "gov", "edu", "co", "ac", "mil", "sch", "gob", "nic", "biz", "info"}


def registrable_domain(host: str) -> str:
    host = host.lower().strip(".").removeprefix("www.")
    parts = host.split(".")
    country_style = len(parts[-1]) == 2 and parts[-2] in SECOND_LEVEL
    if len(parts) >= 3 and (country_style or ".".join(parts[-2:]) in TWO_PART_TLDS | FREE_HOSTS):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def host_of(url: str) -> str:
    u = re.sub(r"(?i)^https?://", "", url)
    return u.split("/")[0].split("?")[0].split(":")[0].lower().removeprefix("www.")


def extract(text: str) -> Entities:
    ents = Entities(text=text)
    no_email = EMAIL_RE.sub(" ", text)
    for m in URL_RE.finditer(no_email):
        url = m.group(1).rstrip(".,);:!?")
        host = host_of(url)
        if "." not in host or host.replace(".", "").isdigit():
            continue
        if url not in ents.urls:
            ents.urls.append(url)
        dom = registrable_domain(host)
        if dom not in ents.domains:
            ents.domains.append(dom)
    for m in PHONE_RE.finditer(text):
        phone = "0" + "".join(m.groups())
        if phone not in ents.phones:
            ents.phones.append(phone)
    digits_in_phones = {p[1:] for p in ents.phones}
    for m in ACCOUNT_RE.finditer(text):
        acct = m.group(0)
        if acct not in ents.accounts and acct not in digits_in_phones:
            ents.accounts.append(acct)
    for m in HANDLE_RE.finditer(EMAIL_RE.sub(" ", text)):
        h = m.group(1).lower()
        if h not in ents.handles:
            ents.handles.append(h)
    for m in NAME_RE.finditer(text):
        name = m.group(1).strip()
        if len(name.split()) >= 2 and name not in ents.names:
            ents.names.append(name)
    return ents
