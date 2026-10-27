"""What Nigerian regulators (SEC, FCCPC) have said: a cited snapshot plus live SEC warnings from `refresh`."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from ..evidence import CAUTION, INFO, SCAM, Entities, Evidence
from ..store import Store

DATA = Path(__file__).resolve().parent.parent / "data" / "regulators.json"

# SEC Nigeria lists its circulars here. Links whose text looks like a warning are followed.
SEC_INDEXES = [
    "https://www.sec.gov.ng/for-investors/keep-track-of-circulars/",
    "https://home.sec.gov.ng/for-investors/keep-track-of-circulars/",
]
WARNING_LINK = re.compile(r"(?i)(public notice|warn|unregistered|illegal|ponzi|caution|alert|scam)")
# "Illegal Operator Alert – CBEX (Crypto Bridge Exchange) June 5, 2025" -> "CBEX (Crypto Bridge Exchange)"
SUBJECT = re.compile(
    r"(?i)^(?:illegal operator(?: alert)?|public notice(?: on)?|investors? alert|scammer alert|public alert on the activities of)"
    r"\s*[-–—:]?\s*(?P<subject>.+?)\s*(?:(?:jan|feb|mar|apr|may|june?|july?|aug|sept?|oct|nov|dec)[a-z]*\.?\s+\d{1,2},\s+\d{4})?$")
DATE = re.compile(r"(?i)((?:jan|feb|mar|apr|may|june?|july?|aug|sept?|oct|nov|dec)[a-z]*\.?\s+\d{1,2},\s+\d{4})\s*$")
GENERIC = {"limited", "ltd", "investment", "investments", "online", "nigeria", "the", "and", "global", "society", "cooperative",
           "forex", "trading", "coin", "exchange", "capital", "ventures", "technology", "technologies", "international",
           "federal republic of nigeria", "unregistered online investment schemes"}
# Notices that aren't about a named bad actor (procedures, lifted suspensions, general topics).
NOT_A_WARNING = re.compile(r"(?i)(dividend|penalt|fidelity bond|implementation|in the matter of claims|suspension|lifts|"
                           r"postpone|scorecard|retail foreign exchange|warrants|^\d|^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))")


_from_data_layer: dict = {}


def use(warned: list[dict], rules: list[dict], notices: list[tuple[str, str, str, str, str]]) -> None:
    """Serve warnings, rules and SEC notices from the data layer (Zetaris) instead of the bundled file and local index."""
    _from_data_layer.update(warned=warned, rules=rules, notices=notices)


def snapshot() -> dict:
    return _from_data_layer or _bundled()


@lru_cache(maxsize=1)
def _bundled() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _found(alias: str, text: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text))


def check(ents: Entities, topics: set[str], store: Store) -> list[Evidence]:
    out: list[Evidence] = []
    text = ents.text.lower()
    named: set[str] = set()
    for w in snapshot()["warned"]:
        if any(_found(a, text) for a in w["aliases"]):
            named.add(w["name"].lower())
            out.append(Evidence(w["regulator"], w["finding"], SCAM, 4, w["url"]))
    for alias, name, title, url, regulator in _from_data_layer.get("notices") or store.warned_aliases():
        if name.lower() in named or not _found(alias, text):
            continue
        named.add(name.lower())
        when = DATE.search(title)
        out.append(Evidence(regulator, f"{regulator} has publicly warned about \"{name}\" (notice: \"{title}\")."
                            + (f" Published {when.group(1)}." if when else ""), SCAM, 4, url))
    for rule in snapshot()["rules"]:
        if rule["when"] in topics:
            out.append(Evidence(rule["regulator"], rule["finding"], CAUTION if rule["when"] == "investment" else INFO, 1, rule["url"]))
    return out


def _decode(raw: bytes) -> str:
    """SEC pages mix UTF-8 with Windows-1252 dashes and quotes."""
    text = raw.decode("utf-8", "replace")
    return raw.decode("cp1252", "replace") if "�" in text else text


def _text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = text.replace("&#8211;", "–").replace("&#8212;", "—").replace("&amp;", "&").replace("&#8217;", "'").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def subject_aliases(title: str) -> tuple[str, list[str]] | None:
    """Operator name and the spellings worth matching, from a notice title. None for non-warning notices."""
    if title.lower().startswith("re:"):
        return None
    m = SUBJECT.match(title.strip())
    if not m:
        return None
    subject = re.sub(r"(?i)\s*disclaimer$", "", m.group("subject")).strip(" -–—:!_\"'“”‘’")
    subject = subject.replace("“", "").replace("”", "").replace('"', "")
    if not subject or subject.lower() in GENERIC or len(subject) > 90 or NOT_A_WARNING.search(subject):
        return None
    parts = re.split(r"(?i)\s*/\s*|\s+and\s+|\s*\(\s*|\s*\)\s*-?\s*|\s+[-–—]\s+|(?<=[A-Za-z])-(?=[A-Z])", subject)
    parts += [t for t in re.findall(r"\b[A-Z]{3,8}\b", subject) if t.lower() not in GENERIC]  # MMM, CBEX, PWAN
    aliases: list[str] = []
    for p in parts if len(parts) > 1 else [subject]:
        p = p.strip(" .,-–—$").lower()
        base = re.sub(r"\s+(limited|ltd|plc|inc)\.?$", "", p)
        for a in {p, base}:
            if len(a) >= 3 and a not in GENERIC and a not in aliases:
                aliases.append(a)
    return subject, aliases


async def refresh(store: Store, client: httpx.AsyncClient, limit: int = 80) -> int:
    """Pull SEC warning notices into the local index and extract the operators they name."""
    links: dict[str, tuple[str, str]] = {}  # path -> (url, label); one entry per notice even though SEC has two hostnames
    for index in SEC_INDEXES:
        try:
            r = await client.get(index, timeout=20, follow_redirects=True)
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        html = _decode(r.content)
        for href, label in re.findall(r"(?is)<a[^>]+href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", html):
            label = _text(label)
            url = urljoin(str(r.url), href)
            path = urlparse(url).path.rstrip("/")
            if "keep-track-of-circulars/" in url and (WARNING_LINK.search(label) or WARNING_LINK.search(href)):
                links.setdefault(path, (url, label))
    saved = 0
    warned: list[tuple[str, str, str, str]] = []
    for url, label in list(links.values())[:limit]:
        try:
            r = await client.get(url, timeout=20, follow_redirects=True)
        except httpx.HTTPError:
            continue
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            continue
        title = label.replace("�", "–") or url
        store.put_notice(title, _text(_decode(r.content))[:20_000], url, "SEC Nigeria")
        saved += 1
        parsed = subject_aliases(title)
        if parsed:
            name, aliases = parsed
            warned += [(a, name, title, url) for a in aliases]
    if warned:
        store.replace_warned("SEC Nigeria", warned)
    return saved
