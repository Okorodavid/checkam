"""The investigation: find what's checkable, run every source at once, number the evidence, decide."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from .config import Settings
from .evidence import Entities, Evidence, extract, host_of, registrable_domain
from .hmem import HMEM
from .reasoner import Verdict, decide
from .sources import links, memory, official, patterns, regulators, threats, websearch
from .store import Store

log = logging.getLogger("checkam.agent")


@dataclass
class Report:
    message: str
    entities: Entities
    evidence: list[Evidence]
    verdict: Verdict
    seconds: float


class Checker:
    def __init__(self, settings: Settings, store: Store, client: httpx.AsyncClient | None = None,
                 hmem: HMEM | None = None):
        self.settings = settings
        self.store = store
        self.hmem = hmem or HMEM(store.path)  # H-MEM tables live in the same SQLite file
        self.client = client or httpx.AsyncClient(headers={"User-Agent": links.UA["User-Agent"]})

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _expand_short_links(self, ents: Entities) -> list[Evidence]:
        out = []
        for url in [u for u in ents.urls if threats.is_shortener(host_of(u))][:2]:
            final = await links.expand(self.client, url)
            if not final:
                continue
            out.append(Evidence(threats.SOURCE, f"The short link {host_of(url)} really opens {host_of(final)}.", "info", 0, final))
            ents.urls.append(final)
            dom = registrable_domain(host_of(final))
            if dom not in ents.domains:
                ents.domains.append(dom)
        return out

    async def check(self, message: str, platform: str = "cli", user: str = "local") -> Report:
        started = time.monotonic()
        ents = extract(message)
        evidence: list[Evidence] = []

        evidence += await self._expand_short_links(ents)
        found, topics = patterns.scan(message)
        evidence += found
        evidence += threats.check(ents, self.store)
        evidence += official.check(ents)
        evidence += regulators.check(ents, topics, self.store)
        evidence += memory.check(ents, self.hmem, user)  # replaces reports.check: same signal, now from H-MEM

        slow = await asyncio.gather(
            links.check(ents, self.store, self.client),
            websearch.check(ents, self.settings.tavily_api_key, self.client),
            threats.safe_browsing(ents.urls[:4], self.settings.safe_browsing_key, self.client),
            threats.urlhaus(ents.urls[:2], self.settings.urlhaus_auth_key, self.client),
            return_exceptions=True,
        )
        for part in slow:
            if isinstance(part, list):
                evidence += part
            elif isinstance(part, Exception):
                log.warning("source failed: %r", part)

        evidence = dedupe(evidence)
        for i, e in enumerate(evidence, 1):
            e.id = f"E{i}"

        verdict = await decide(self.settings, message, evidence, self.client)
        self.store.record(platform, user, ents.lookups(), verdict.verdict)
        memory.remember(self.hmem, ents, verdict.verdict, platform, user)
        return Report(message, ents, evidence, verdict, time.monotonic() - started)


def dedupe(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[str] = set()
    out = []
    for e in evidence:
        if e.finding not in seen:
            seen.add(e.finding)
            out.append(e)
    # strongest first, so both the model and the reader see what matters most
    order = {"scam": 0, "caution": 1, "safe": 2, "info": 3}
    return sorted(out, key=lambda e: (order.get(e.signal, 4), -e.weight))
