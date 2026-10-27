"""Does the message pretend to be a real company? Compare its links and @handles with the real ones."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..evidence import CAUTION, SAFE, SCAM, Entities, Evidence

SOURCE = "Official accounts list"
DATA = Path(__file__).resolve().parent.parent / "data" / "official.json"


@dataclass(frozen=True)
class Org:
    name: str
    kind: str
    aliases: tuple[str, ...]
    domains: tuple[str, ...]
    x: tuple[str, ...]

    def site(self) -> str:
        return self.domains[0] if self.domains else ""


_from_data_layer: tuple[Org, ...] = ()


def use(orgs: list[Org]) -> None:
    """Serve the list from the data layer (Zetaris) instead of the bundled file."""
    global _from_data_layer
    _from_data_layer = tuple(orgs)


def registry() -> tuple[Org, ...]:
    return _from_data_layer or _bundled()


@lru_cache(maxsize=1)
def _bundled() -> tuple[Org, ...]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))["orgs"]
    return tuple(Org(o["name"], o["kind"], tuple(a.lower() for a in o["aliases"]),
                     tuple(d.lower() for d in o["domains"]), tuple(h.lower() for h in o["x"])) for o in raw)


def mentioned(text: str) -> list[Org]:
    t = text.lower()
    return [o for o in registry() if any(re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", t) for a in o.aliases)]


def owner_of(domain: str) -> Org | None:
    for o in registry():
        if any(domain == d or domain.endswith("." + d) for d in o.domains):
            return o
    return None


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def lookalike(domain: str) -> Org | None:
    """A domain that borrows a brand's name or is one typo away from its real site."""
    if owner_of(domain):
        return None
    label = domain.split(".")[0]
    for o in registry():
        for real in o.domains:
            real_label = real.split(".")[0]
            if len(real_label) >= 4 and (real_label in label or _edit_distance(label, real_label) <= 1):
                return o
        for a in o.aliases:
            a2 = a.replace(" ", "")
            if len(a2) >= 4 and a2 in label.replace("-", ""):
                return o
    return None


def check(ents: Entities) -> list[Evidence]:
    out: list[Evidence] = []
    brands = mentioned(ents.text)
    for dom in ents.domains:
        real = owner_of(dom)
        if real:
            out.append(Evidence(SOURCE, f"{dom} is {real.name}'s real website.", SAFE, 1, f"https://{real.site()}"))
            continue
        fake = lookalike(dom)
        if fake:
            out.append(Evidence(SOURCE, f"{dom} looks like {fake.name}'s name but is not their website. {fake.name}'s real site is {fake.site()}.",
                                SCAM, 3, f"https://{fake.site()}"))
            continue
        for b in brands:
            out.append(Evidence(SOURCE, f"The message mentions {b.name}, but the link goes to {dom}, which is not one of {b.name}'s websites ({b.site()}).",
                                SCAM, 3, f"https://{b.site()}"))
    for h in ents.handles:
        owner = next((o for o in registry() if h in o.x), None)
        if owner:
            out.append(Evidence(SOURCE, f"@{h} is {owner.name}'s official X account.", SAFE, 1, f"https://x.com/{h}"))
            continue
        for o in registry():
            if o.x and any(a.replace(" ", "") in h for a in o.aliases if len(a.replace(" ", "")) >= 3):
                real = ", ".join("@" + x for x in o.x)
                out.append(Evidence(SOURCE, f"@{h} uses {o.name}'s name but is not on our list of {o.name}'s official accounts ({real}). "
                                    "Fake 'support' accounts copy real names.", CAUTION, 2, f"https://x.com/{o.x[0]}"))
                break
    return out
