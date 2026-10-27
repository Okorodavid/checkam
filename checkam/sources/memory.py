"""CheckAm memory (H-MEM): has CheckAm seen this account number, phone, website or @handle before?

After each check, one H-MEM memory per lookup scammers reuse, e.g. "Account 8123456789 was in a
message CheckAm judged scam (telegram)". Only that line, the verdict, the platform and the salted
user key are kept; message text is never stored. Before deciding, H-MEM is queried for the same
values and what other people's checks found becomes evidence. Your own past checks never count.
"""

from __future__ import annotations

from ..evidence import CAUTION, INFO, SCAM, Entities, Evidence
from ..hmem import HMEM, MemoryRecord, Provenance

SOURCE = "CheckAm memory (H-MEM)"
WRITER = "checkam-check"
LABEL = {"account": "account number", "phone": "phone number", "domain": "website", "handle": "account"}
SEVERITY = ("scam", "likely_scam", "not_sure", "looks_safe")


def _shown(kind: str, value: str) -> str:
    return f"@{value}" if kind == "handle" else value


def _subject(kind: str, value: str) -> str:
    return f"{LABEL[kind].capitalize()} {_shown(kind, value)}"


def _tag(m: MemoryRecord, prefix: str) -> str:
    return next((t[len(prefix):] for t in m.tags if t.startswith(prefix)), "")


def recall(hmem: HMEM, kind: str, value: str, user: str) -> list[MemoryRecord]:
    """Other people's memories about this exact value, best first."""
    entity = f"{kind}:{value}"
    result = hmem.query(f"{_subject(kind, value)} was in a message CheckAm judged", entities=[entity], top_n=20)
    # H-MEM ranks; the exact entity match keeps a look-alike number from counting
    return [r.memory for r in result.memories
            if entity in r.memory.entities and r.memory.source == WRITER and _tag(r.memory, "user:") != user]


def check(ents: Entities, hmem: HMEM, user: str) -> list[Evidence]:
    out: list[Evidence] = []
    for kind, value in ents.lookups():
        found = recall(hmem, kind, value, user)
        if not found:
            continue
        people = {_tag(m, "user:") for m in found}
        verdicts = sorted({_tag(m, "verdict:") for m in found}, key=lambda v: SEVERITY.index(v) if v in SEVERITY else 9)
        n = len(people)
        who = "1 other person" if n == 1 else f"{n} other people"
        said = ", ".join(v.replace("_", " ") for v in verdicts)
        finding = f"{who} sent me this same {LABEL[kind]} ({_shown(kind, value)}) before. My verdict then: {said}."
        if verdicts == ["looks_safe"]:
            out.append(Evidence(SOURCE, finding, INFO, 0))
        else:
            out.append(Evidence(SOURCE, finding, SCAM if n >= 3 else CAUTION, 3 if n >= 3 else 2))
    return out


def remember(hmem: HMEM, ents: Entities, verdict: str, platform: str, user: str) -> list[MemoryRecord]:
    """Write what this check saw. A repeat of the same value, verdict and user refreshes the old memory."""
    hmem.store.sync()  # see memories another process wrote
    out = []
    for kind, value in ents.lookups():
        entity = f"{kind}:{value}"
        tags = [f"verdict:{verdict}", f"platform:{platform}", f"user:{user}", f"kind:{kind}"]
        same = next((m for m in hmem.store.all() if m.source == WRITER and entity in m.entities
                     and f"user:{user}" in m.tags and f"verdict:{verdict}" in m.tags), None)
        if same:
            out.append(hmem.store.update(same.id, last_accessed=hmem.clock(), access_count=same.access_count + 1))
            continue
        out.append(hmem.add(
            f"{_subject(kind, value)} was in a message CheckAm judged {verdict} ({platform})", WRITER,
            type="factual", tags=tags, entities=[entity], confidence=0.8,
            provenance=Provenance("model_response", hmem.clock(), f"CheckAm {platform} check")))
    return out
