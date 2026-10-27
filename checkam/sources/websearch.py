"""Optional web and X search through Tavily: what are people and news sites saying about this name or site?"""

from __future__ import annotations

import re

import httpx

from ..evidence import CAUTION, INFO, Entities, Evidence

SOURCE = "Web and X search"
ALARM = re.compile(r"(?i)\b(scam|fraud|ponzi|fake|warn(ing|s|ed)?|beware|illegal|unregistered|duped|stole|crash(ed)?|collapse[sd]?|arrest(ed)?)\b")


def queries(ents: Entities) -> list[tuple[str, list[str] | None]]:
    subject = (ents.names[:1] or [d for d in ents.domains[:1]] or [f"@{h}" for h in ents.handles[:1]])
    if not subject:
        return []
    s = subject[0]
    return [(f"\"{s}\" scam OR fraud OR warning Nigeria", None), (f"\"{s}\"", ["x.com", "twitter.com"])]


async def check(ents: Entities, api_key: str, client: httpx.AsyncClient) -> list[Evidence]:
    if not api_key:
        return []
    out: list[Evidence] = []
    seen: set[str] = set()
    for query, domains in queries(ents):
        body: dict = {"query": query, "max_results": 5, "search_depth": "basic"}
        if domains:
            body["include_domains"] = domains
        try:
            r = await client.post("https://api.tavily.com/search", json=body, timeout=15,
                                  headers={"Authorization": f"Bearer {api_key}"})
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        for item in r.json().get("results", [])[:5]:
            url, title, content = item.get("url", ""), item.get("title", ""), item.get("content", "")
            if not url or url in seen:
                continue
            seen.add(url)
            on_x = "x.com" in url or "twitter.com" in url
            where = "A post on X" if on_x else "A web page"
            if ALARM.search(f"{title} {content}"):
                snippet = re.sub(r"\s+", " ", content).strip()[:140]
                out.append(Evidence(SOURCE, f"{where} warns about it: \"{snippet}…\"", CAUTION, 2, url))
            elif on_x:
                out.append(Evidence(SOURCE, f"{where} mentions it: \"{title[:100]}\"", INFO, 0, url))
        if len(out) >= 4:
            break
    return out[:4]
