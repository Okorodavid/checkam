"""Has anyone else sent CheckAm the same account number, phone, website or @handle?"""

from __future__ import annotations

import time

from ..evidence import CAUTION, SCAM, Entities, Evidence
from ..store import Store

SOURCE = "Other CheckAm users"
WINDOW_DAYS = 30
LABEL = {"account": "account number", "phone": "phone number", "domain": "website", "handle": "account @"}


def check(ents: Entities, store: Store, user: str, now: float | None = None) -> list[Evidence]:
    now = time.time() if now is None else now
    out: list[Evidence] = []
    for kind, value in ents.lookups():
        n = store.others_reporting(kind, value, user, now - WINDOW_DAYS * 86400)
        if n == 0:
            continue
        shown = f"@{value}" if kind == "handle" else value
        people = "1 other person" if n == 1 else f"{n} other people"
        out.append(Evidence(SOURCE, f"{people} sent me this same {LABEL[kind].rstrip(' @')} ({shown}) in the last {WINDOW_DAYS} days.",
                            SCAM if n >= 3 else CAUTION, 3 if n >= 3 else 2))
    return out
