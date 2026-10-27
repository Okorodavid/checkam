"""H-MEM memory engine (Meterless), a Python port of the reference in engines/hmem.

One record shape, hybrid ranked recall, exact feedback deltas, an append-only trust ledger,
conflict detection with a 0.70 auto-resolve gate, a preview-first sleep cycle with backups,
and dreaming behind a human approval boundary. Constants and formulas match AGENTS.md and
reference/src so the conformance vectors pass unchanged.

Persistence: give `db_path` and the working + long_term tiers (plus the ledger) live in
SQLite tables next to CheckAm's own; short_term stays in memory. Without it, all in memory.
"""

from __future__ import annotations

import copy
import json
import math
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Callable

DAY_MS = 24 * 60 * 60 * 1000
FEEDBACK_DELTAS = {"helpful": 0.05, "not_helpful": -0.03, "wrong": -0.2}
DEFAULTS = {
    "retrieval_top_n": 5,
    "retrieval_threshold": 0.35,  # on the final score, after the confidence multiplier
    "consolidation_days": 7,
    "archive_min_days": 30,
    "archive_max_access": 2,
    "synthesis_cosine": 0.82,
    "dream_cluster_min_size": 2,
    "dream_relatedness": 0.35,
    "max_dream_proposals_per_type": 8,
    "conflict_auto_resolve_gate": 0.7,
    "entity_cap": 10,
    "related_cap": 5,
    "recency_days": 14,
}
LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}
DURABLE = ("working", "long_term")
LEDGER_ACTIONS = ("create", "read", "update", "delete", "feedback", "promote", "demote", "merge",
                  "conflict_detected", "conflict_resolved", "sleep_consolidate", "sleep_archive",
                  "sleep_synthesize", "dream_proposed", "dream_approved", "dream_rejected", "restore")
HUB_THRESHOLD = 3


def clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


# ---------------------------------------------------------------- embeddings

DIM = 64


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\s+", re.sub(r"[^a-z0-9\s]", " ", text.lower())) if len(t) > 1]


def _fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def embed(text: str) -> list[float]:
    """Deterministic local embedder: FNV-1a per token into 64 dims, L2-normalised. No network."""
    vec = [0.0] * DIM
    for token in tokenize(text):
        h = _fnv1a(token)
        sign = 1 if (h >> 8) % 2 == 0 else -1
        vec[h % DIM] += sign * (1 + ((h >> 16) % 8) / 8)
    norm = math.sqrt(sum(v * v for v in vec))
    return vec if norm == 0 else [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # both unit length


def jaccard(a, b) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / (len(sa) + len(sb) - inter)


# ---------------------------------------------------------------- records

@dataclass
class Provenance:
    origin: str  # chat_message, user_correction, ..., manual, dream, sleep_synthesis
    learned_at: float
    label: str
    refs: list[str] | None = None


@dataclass
class MemoryRecord:
    id: str
    content: str
    type: str  # personal | factual | preference | general
    layer: str  # short_term | working | long_term
    timestamp: float
    last_accessed: float
    access_count: int
    tags: list[str]
    confidence: float
    source: str
    provenance: Provenance
    domain: str
    namespace: str
    entities: list[str] = field(default_factory=list)  # cap 10
    related_to: list[str] = field(default_factory=list)  # cap 5
    supersedes: str | None = None
    superseded_by: str | None = None
    derived_from: list[str] | None = None
    chat_id: str | None = None
    mission_id: str | None = None
    goal_run_id: str | None = None
    embedding: list[float] = field(default_factory=list, repr=False)
    score: float | None = None


def snapshot(r: MemoryRecord) -> dict:
    d = asdict(r)
    d.pop("embedding", None)
    d.pop("score", None)
    return d


def _from_dict(d: dict) -> MemoryRecord:
    names = {f.name for f in fields(MemoryRecord)}
    d = {k: v for k, v in d.items() if k in names}
    d["provenance"] = Provenance(**d["provenance"])
    rec = MemoryRecord(**d)
    rec.embedding = embed(rec.content)  # backfill on load
    return rec


@dataclass
class LedgerEntry:
    memory_id: str
    action: str
    actor: str
    timestamp: float
    previous_state: dict | None = None
    new_state: dict | None = None
    details: dict | None = None


@dataclass
class RetrievedMemory:
    memory: MemoryRecord
    relevance: float


@dataclass
class QueryResult:
    memories: list[RetrievedMemory]
    context: str
    trace: dict


@dataclass
class ConflictRecord:
    id: str
    memory_a: str
    memory_b: str
    reason: str
    confidence: float
    resolved: bool = False
    resolution: str | None = None  # keep_a | keep_b | keep_both | merge | delete_both


@dataclass
class DreamProposal:
    id: str
    type: str  # insight | domain | invariant
    content: str
    derived_from: list[str]
    suggested_domain: str | None = None
    status: str = "proposed"


@dataclass
class SleepPreview:
    to_consolidate: list[str]
    to_archive: list[str]
    to_synthesize: list[list[str]]


@dataclass
class SleepReport:
    backup_id: str
    consolidated: int
    archived: int
    synthesized: int
    action_log: list[str]


# ---------------------------------------------------------------- persistence

SCHEMA = """
CREATE TABLE IF NOT EXISTS hmem_memories (id TEXT PRIMARY KEY, layer TEXT, record TEXT);
CREATE TABLE IF NOT EXISTS hmem_ledger (ts REAL, memory_id TEXT, action TEXT, actor TEXT, entry TEXT);
CREATE INDEX IF NOT EXISTS hmem_ledger_memory ON hmem_ledger(memory_id);
CREATE TABLE IF NOT EXISTS hmem_meta (key TEXT PRIMARY KEY, value TEXT);
"""


class _DB:
    def __init__(self, path: Path | str):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.executescript(SCHEMA)

    def version(self) -> int:
        return int(self.db.execute("PRAGMA data_version").fetchone()[0])

    def next_seq(self) -> int:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO hmem_meta VALUES ('seq', '0')")
            self.db.execute("UPDATE hmem_meta SET value = CAST(value AS INTEGER) + 1 WHERE key='seq'")
            return int(self.db.execute("SELECT value FROM hmem_meta WHERE key='seq'").fetchone()[0])

    def set_seq(self, seq: int) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO hmem_meta VALUES ('seq', ?)", (str(seq),))

    def seq(self) -> int:
        row = self.db.execute("SELECT value FROM hmem_meta WHERE key='seq'").fetchone()
        return int(row[0]) if row else 0

    def save(self, recs: list[MemoryRecord]) -> None:
        with self.lock, self.db:
            for r in recs:
                if r.layer in DURABLE:
                    self.db.execute("INSERT OR REPLACE INTO hmem_memories VALUES (?,?,?)",
                                    (r.id, r.layer, json.dumps(snapshot(r))))
                else:
                    self.db.execute("DELETE FROM hmem_memories WHERE id=?", (r.id,))

    def drop(self, memory_id: str) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM hmem_memories WHERE id=?", (memory_id,))

    def replace_all(self, recs: list[MemoryRecord]) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM hmem_memories")
        self.save(recs)

    def load(self) -> list[MemoryRecord]:
        rows = self.db.execute("SELECT record FROM hmem_memories WHERE layer IN ('working','long_term')").fetchall()
        return [_from_dict(json.loads(r[0])) for r in rows]

    def append(self, e: LedgerEntry) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO hmem_ledger VALUES (?,?,?,?,?)",
                            (e.timestamp, e.memory_id, e.action, e.actor, json.dumps(asdict(e))))

    def ledger(self) -> list[LedgerEntry]:
        return [LedgerEntry(**json.loads(r[0])) for r in self.db.execute("SELECT entry FROM hmem_ledger ORDER BY rowid")]


# ---------------------------------------------------------------- trust ledger

class TrustLedgerService:
    """Append-only. Entries are never mutated or deleted; history() rebuilds a memory's changes."""

    def __init__(self, clock: Callable[[], float], db: _DB | None = None):
        self.clock = clock
        self.db = db
        self.entries: list[LedgerEntry] = db.ledger() if db else []

    def log(self, memory_id: str, action: str, actor: str, previous_state: dict | None = None,
            new_state: dict | None = None, details: dict | None = None) -> LedgerEntry:
        if action not in LEDGER_ACTIONS:
            raise ValueError(f"H-MEM: unknown ledger action {action}")
        entry = LedgerEntry(memory_id, action, actor, self.clock(), previous_state, new_state, details)
        self.entries.append(entry)
        if self.db:
            self.db.append(entry)
        return entry

    def history(self, memory_id: str) -> list[LedgerEntry]:
        return [e for e in self.entries if e.memory_id == memory_id]

    def all(self) -> list[LedgerEntry]:
        return list(self.entries)

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.action] = out.get(e.action, 0) + 1
        return out


# ---------------------------------------------------------------- store + enrichment

TECH_TERMS = ["react", "python", "typescript", "javascript", "rust", "sqlite", "postgres", "indexeddb",
              "node", "docker", "graphql", "redis", "webrtc", "tauri", "electron", "llm", "embedding"]
DOMAIN_KEYWORDS = {
    "tech": ["code", "bug", "api", "database", "deploy", "framework", "library", "server", *TECH_TERMS],
    "work": ["meeting", "deadline", "client", "project", "sprint", "review", "report"],
    "personal": ["family", "hobby", "prefer", "like", "dislike", "morning", "evening"],
}
CORRECTION = re.compile(r"\b(actually|instead|no longer|not anymore|changed to|correction)\b", re.I)


class MemoryStoreService:
    def __init__(self, clock: Callable[[], float], ledger: TrustLedgerService, actor: str, db: _DB | None = None):
        self.clock = clock
        self.ledger = ledger
        self.actor = actor
        self.db = db
        self.records: dict[str, MemoryRecord] = {}
        self._seq = 0
        self._version = -1
        self.sync()

    def sync(self) -> None:
        """Pick up durable tiers written by another process; short_term stays as it is."""
        if not self.db or self.db.version() == self._version:
            return
        self._version = self.db.version()
        short = {k: r for k, r in self.records.items() if r.layer == "short_term"}
        self.records = {r.id: r for r in self.db.load()}
        self.records.update(short)
        self._seq = self.db.seq()

    def _next_id(self) -> str:
        self._seq = self.db.next_seq() if self.db else self._seq + 1
        return f"mem-{self._seq}"

    def persist(self, *recs: MemoryRecord) -> None:
        if self.db:
            self.db.save(list(recs) if recs else list(self.records.values()))
            self._version = self.db.version()

    def add(self, content: str, source: str, type: str = "general", layer: str = "working",
            tags: list[str] | None = None, confidence: float = 0.7, provenance: Provenance | None = None,
            entities: list[str] | None = None, chat_id: str | None = None, mission_id: str | None = None,
            goal_run_id: str | None = None, supersedes: str | None = None,
            derived_from: list[str] | None = None) -> MemoryRecord:
        if not source or not str(source).strip():
            raise ValueError("H-MEM: a memory record with no source must be rejected by construction (AGENTS.md section 2)")
        now = self.clock()
        tags = list(tags or [])
        domain = self.classify_domain(content, tags, type)
        ents = _norm_entities(entities) if entities is not None else self.extract_entities(content)
        rec = MemoryRecord(
            id=self._next_id(), content=content, type=type, layer=layer, timestamp=now, last_accessed=now,
            access_count=0, tags=tags, confidence=clamp01(confidence), source=source,
            provenance=provenance or Provenance("manual", now, source), domain=domain,
            namespace=self._namespace(domain, type), entities=ents, related_to=[], supersedes=supersedes,
            derived_from=derived_from, chat_id=chat_id, mission_id=mission_id, goal_run_id=goal_run_id,
            embedding=embed(content))
        touched = self._discover_relationships(rec)
        self.records[rec.id] = rec
        self.ledger.log(rec.id, "create", self.actor, new_state=snapshot(rec))
        self.persist(rec, *touched)
        return rec

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.records.get(memory_id)

    def all(self) -> list[MemoryRecord]:
        return list(self.records.values())

    def update(self, memory_id: str, **patch) -> MemoryRecord:
        rec = self._must(memory_id)
        prev = snapshot(rec)
        for k, v in patch.items():
            setattr(rec, k, v)
        if "content" in patch:
            rec.embedding = embed(rec.content)
        self.ledger.log(memory_id, "update", self.actor, previous_state=prev, new_state=snapshot(rec))
        self.persist(rec)
        return rec

    def delete(self, memory_id: str, reason: str) -> None:
        rec = self._must(memory_id)
        del self.records[memory_id]
        self.ledger.log(memory_id, "delete", self.actor, previous_state=snapshot(rec), details={"reason": reason})
        if self.db:
            self.db.drop(memory_id)
            self._version = self.db.version()

    def touch(self, memory_id: str) -> None:
        rec = self._must(memory_id)
        rec.last_accessed = self.clock()
        rec.access_count += 1

    def promote(self, memory_id: str, layer: str) -> None:
        rec = self._must(memory_id)
        prev = snapshot(rec)
        rec.layer = layer
        self.ledger.log(memory_id, "promote", self.actor, previous_state=prev, new_state=snapshot(rec))
        self.persist(rec)

    def snapshot_all(self) -> tuple[list[MemoryRecord], int]:
        return copy.deepcopy(list(self.records.values())), self._seq

    def restore_all(self, records: list[MemoryRecord], seq: int) -> None:
        self.records = {r.id: copy.deepcopy(r) for r in records}
        self._seq = seq
        if self.db:
            self.db.replace_all(list(self.records.values()))
            self.db.set_seq(seq)
            self._version = self.db.version()

    def _must(self, memory_id: str) -> MemoryRecord:
        rec = self.records.get(memory_id)
        if rec is None:
            raise KeyError(f"H-MEM: unknown memory id {memory_id}")
        return rec

    def classify_domain(self, content: str, tags: list[str], type: str) -> str:
        for t in tags:
            if t.startswith("project:"):
                return t[len("project:"):]
            if t.startswith("tech:"):
                return "tech"
        tokens = set(tokenize(content))
        best, best_score = "general", 0
        for domain, kws in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in kws if kw in tokens)
            if domain == "personal" and type in ("personal", "preference"):
                score += 1
            if score > best_score:
                best, best_score = domain, score
        return best if best_score > 0 else "general"

    @staticmethod
    def _namespace(domain: str, type: str) -> str:
        bucket = "profile" if type in ("preference", "personal") else "facts" if type == "factual" else "notes"
        return f"{domain}/{bucket}"

    def extract_entities(self, content: str) -> list[str]:
        out: list[str] = []
        for t in tokenize(content):
            if t in TECH_TERMS and t not in out:
                out.append(t)
        for m in re.finditer(r"\b([A-Z][a-zA-Z]{2,})\b", content):
            norm = m.group(1).lower()
            if norm not in ("the", "this", "that", "with") and norm not in out:
                out.append(norm)
        return out[:DEFAULTS["entity_cap"]]

    def _discover_relationships(self, rec: MemoryRecord) -> list[MemoryRecord]:
        touched = []
        for other in self.records.values():
            if len(rec.related_to) >= DEFAULTS["related_cap"]:
                break
            shared = [e for e in other.entities if e in rec.entities]
            sim = cosine(rec.embedding, other.embedding)
            if not rec.supersedes and sim > 0.85 and CORRECTION.search(rec.content):
                rec.supersedes = other.id
                continue
            if shared and other.domain == rec.domain:
                rec.related_to.append(other.id)
                if len(other.related_to) < DEFAULTS["related_cap"] and rec.id not in other.related_to:
                    other.related_to.append(rec.id)  # bidirectional link
                    touched.append(other)
        return touched


def _norm_entities(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        v = str(v).strip().lower()
        if v and v not in out:
            out.append(v)
    return out[:DEFAULTS["entity_cap"]]


# ---------------------------------------------------------------- retrieval

class MemoryRetrievalService:
    """raw = .35 semantic + .20 keyword + .10 tag + .10 domain + .15 entity + .05 layer + .05 recency - .20 superseded;
    score = clamp01(raw) * confidence. Threshold applies to the final score."""

    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, clock: Callable[[], float], actor: str):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor

    def _prepare(self, query: str, entities: list[str] | None):
        q_entities = _norm_entities(entities) if entities is not None else self.store.extract_entities(query)
        return embed(query), tokenize(query)[:8], q_entities, self.store.classify_domain(query, [], "general")

    def score_one(self, memory: MemoryRecord, query: str, entities: list[str] | None = None) -> float:
        return self._score(memory, *self._prepare(query, entities))

    def _score(self, m: MemoryRecord, q_emb, q_tokens, q_entities, q_domain) -> float:
        semantic = clamp01(cosine(q_emb, m.embedding))
        keyword = jaccard(q_tokens, tokenize(m.content))
        tag = jaccard(q_tokens, [t.lower() for t in m.tags])
        domain = 1 if m.domain == q_domain else 0
        entity = jaccard(q_entities, m.entities)
        layer = LAYER_WEIGHT[m.layer]
        recency = math.exp(-((self.clock() - m.last_accessed) / DAY_MS) / DEFAULTS["recency_days"])
        superseded = 1 if m.superseded_by else 0
        raw = (0.35 * semantic + 0.2 * keyword + 0.1 * tag + 0.1 * domain
               + 0.15 * entity + 0.05 * layer + 0.05 * recency - 0.2 * superseded)
        return clamp01(raw) * m.confidence

    def query(self, query: str, top_n: int | None = None, threshold: float | None = None,
              chat_id: str | None = None, entities: list[str] | None = None) -> QueryResult:
        self.store.sync()
        prepared = self._prepare(query, entities)
        threshold = DEFAULTS["retrieval_threshold"] if threshold is None else threshold
        top_n = DEFAULTS["retrieval_top_n"] if top_n is None else top_n
        scored = []
        for m in self.store.all():
            if chat_id and m.chat_id and m.chat_id != chat_id:
                continue
            s = self._score(m, *prepared)
            if s >= threshold:
                scored.append(RetrievedMemory(m, s))
        scored.sort(key=lambda r: (-r.relevance, r.memory.id))
        top = scored[:top_n]
        for r in top:
            r.memory.score = r.relevance
            self.store.touch(r.memory.id)
            self.ledger.log(r.memory.id, "read", self.actor, details={"query": query})
        self.store.persist(*[r.memory for r in top])
        if len(top) <= 1:
            strategy = "minimal"
        elif any(r.memory.type in ("personal", "preference") for r in top):
            strategy = "personal"
        else:
            strategy = "comprehensive"
        return QueryResult(top, self.format_reinjection(top), {
            "retrieval_reason": f'hybrid ranking for "{query}" (domain: {prepared[3]})',
            "strategy": strategy,
            "scores": {r.memory.id: round(r.relevance, 4) for r in top},
        })

    @staticmethod
    def format_reinjection(items: list[RetrievedMemory]) -> str:
        if not items:
            return ""
        by_domain: dict[str, list[RetrievedMemory]] = {}
        for it in items:
            by_domain.setdefault(it.memory.domain, []).append(it)
        lines = ["[MEMORY CONTEXT]"]
        for domain in sorted(by_domain):
            lines.append(f"## {domain}")
            for it in by_domain[domain]:
                m = it.memory
                marker = {"long_term": "LT", "working": "WK"}.get(m.layer, "ST")
                ents = f" (entities: {', '.join(m.entities)})" if m.entities else ""
                lines.append(f"- [{marker}] {m.content}{ents} <{m.id}>")
        lines.append("[/MEMORY CONTEXT]")
        return "\n".join(lines)

    def feedback(self, memory_id: str, kind: str) -> None:
        m = self.store.get(memory_id)
        if m is None:
            raise KeyError(f"H-MEM: unknown memory id {memory_id}")
        prev = snapshot(m)
        if kind == "helpful":
            m.access_count += 1
        m.confidence = clamp01(m.confidence + FEEDBACK_DELTAS[kind])
        if kind == "wrong" and "review" not in m.tags:
            m.tags.append("review")
        self.ledger.log(memory_id, "feedback", self.actor, previous_state=prev, new_state=snapshot(m),
                        details={"kind": kind, "delta": FEEDBACK_DELTAS[kind]})
        self.store.persist(m)


# ---------------------------------------------------------------- conflicts

OPPOSING_PAIRS = [
    (re.compile(r"\balways\b", re.I), re.compile(r"\bnever\b", re.I)),
    (re.compile(r"\benable[ds]?\b", re.I), re.compile(r"\bdisable[ds]?\b", re.I)),
    (re.compile(r"\bprefer[s]?\b", re.I), re.compile(r"\bavoid[s]?|dislike[s]?\b", re.I)),
    (re.compile(r"\bon\b", re.I), re.compile(r"\boff\b", re.I)),
    (re.compile(r"\byes\b", re.I), re.compile(r"\bno\b", re.I)),
]
NUM_RE = re.compile(r"\d+(\.\d+)?")


class ConflictDetectionService:
    """The loser is marked superseded_by (kept, penalised in ranking), never deleted."""

    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, clock: Callable[[], float], actor: str):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor
        self.conflicts: list[ConflictRecord] = []
        self._seq = 0

    def scan(self) -> list[ConflictRecord]:
        found = []
        recs = self.store.all()
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                c = self._check(recs[i], recs[j])
                if c:
                    found.append(c)
                    self.conflicts.append(c)
                    self.ledger.log(c.memory_a, "conflict_detected", self.actor,
                                    details={"with": c.memory_b, "reason": c.reason, "confidence": c.confidence})
        return found

    def _check(self, a: MemoryRecord, b: MemoryRecord) -> ConflictRecord | None:
        if b.id in (a.supersedes, a.superseded_by) or a.id in (b.supersedes, b.superseded_by):
            return None  # an intended replacement, not a conflict
        sim = cosine(a.embedding, b.embedding)
        reason, confidence = "", 0.0
        for p, q in OPPOSING_PAIRS:
            if (p.search(a.content) and q.search(b.content)) or (q.search(a.content) and p.search(b.content)):
                if sim > 0.5:
                    reason, confidence = "opposing phrase pair on similar content", 0.5 + 0.3 * sim
        if not reason and sim > 0.8:
            nums_a = [m.group(0) for m in NUM_RE.finditer(a.content)]
            nums_b = [m.group(0) for m in NUM_RE.finditer(b.content)]
            if nums_a and nums_b and nums_a != nums_b:
                reason, confidence = "high-similarity conflicting numeric values", 0.55 + 0.25 * sim
        if not reason:
            return None
        if any(e in b.entities for e in a.entities):
            confidence += 0.1
        if a.domain == b.domain:
            confidence += 0.05
        if b.id in a.related_to:
            confidence -= 0.1  # explicit relation lowers false positives
        self._seq += 1
        return ConflictRecord(f"conflict-{self._seq}", a.id, b.id, reason, clamp01(confidence))

    def auto_resolve(self, conflict: ConflictRecord) -> str:
        a, b = self.store.get(conflict.memory_a), self.store.get(conflict.memory_b)
        now = max(1, self.clock())

        def score(m: MemoryRecord) -> float:
            return (0.3 * (m.last_accessed / now) + 0.2 * min(1, m.access_count / 10) + 0.25 * m.confidence
                    + 0.1 * min(1, len(m.content) / 200)
                    + 0.15 * (1 if m.provenance.origin == "user_correction" else 0.5))

        sa, sb = score(a), score(b)
        margin = abs(sa - sb) / max(sa, sb)
        decision = clamp01(conflict.confidence * 0.6 + margin * 0.8)
        if decision < DEFAULTS["conflict_auto_resolve_gate"]:
            return "queued"
        winner, loser = (a, b) if sa >= sb else (b, a)
        prev = snapshot(loser)
        loser.superseded_by = winner.id
        conflict.resolved = True
        conflict.resolution = "keep_a" if winner.id == conflict.memory_a else "keep_b"
        self.ledger.log(loser.id, "conflict_resolved", self.actor, previous_state=prev, new_state=snapshot(loser),
                        details={"conflict_id": conflict.id, "winner": winner.id, "decision_confidence": round(decision, 3)})
        self.store.persist(loser)
        return "resolved"

    def queue(self) -> list[ConflictRecord]:
        return [c for c in self.conflicts if not c.resolved]


# ---------------------------------------------------------------- sleep cycle

class SleepCycleService:
    """Preview-first: preview() mutates nothing; execute() backs up first; restore() undoes it.
    Never archived: superseding records, derived/synthesised records, relationship hubs."""

    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, clock: Callable[[], float], actor: str):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor
        self.backups: dict[str, tuple[list[MemoryRecord], int]] = {}

    def preview(self) -> SleepPreview:
        now = self.clock()
        recs = self.store.all()
        referenced: set[str] = set()
        for m in recs:
            referenced.update(m.related_to)
            if m.supersedes:
                referenced.add(m.supersedes)
            referenced.update(m.derived_from or [])

        consolidate = [m.id for m in recs if m.layer == "short_term"
                       and now - m.last_accessed >= DEFAULTS["consolidation_days"] * DAY_MS]

        def archivable(m: MemoryRecord) -> bool:
            if not (now - m.timestamp >= DEFAULTS["archive_min_days"] * DAY_MS
                    and m.access_count <= DEFAULTS["archive_max_access"] and m.id not in referenced):
                return False
            return not (m.supersedes or m.derived_from or len(m.related_to) >= HUB_THRESHOLD)

        archive = [m.id for m in recs if archivable(m)]
        synth: list[list[str]] = []
        used: set[str] = set()
        for i, a in enumerate(recs):
            if a.id in used:
                continue
            group = [a] + [b for b in recs[i + 1:] if b.id not in used
                           and cosine(a.embedding, b.embedding) >= DEFAULTS["synthesis_cosine"]]
            if len(group) >= 2:
                used.update(g.id for g in group)
                synth.append([g.id for g in group])
        return SleepPreview(consolidate, archive, synth)

    def execute(self, preview: SleepPreview | None = None) -> SleepReport:
        plan = preview or self.preview()
        backup_id = f"backup-{len(self.backups) + 1}"
        self.backups[backup_id] = self.store.snapshot_all()
        log = [f"backup {backup_id} created"]
        for mid in plan.to_consolidate:
            if self.store.get(mid):
                self.store.promote(mid, "long_term")
                self.ledger.log(mid, "sleep_consolidate", self.actor, details={"from": "short_term", "to": "long_term"})
                log.append(f"consolidated {mid}")
        for mid in plan.to_archive:
            m = self.store.get(mid)
            if m:
                self.ledger.log(mid, "sleep_archive", self.actor,
                                details={"age": self.clock() - m.timestamp, "access_count": m.access_count})
                self.store.delete(mid, "sleep archive")
                log.append(f"archived {mid}")
        synthesized = 0
        for group in plan.to_synthesize:
            members = [m for m in (self.store.get(i) for i in group) if m]
            if len(members) < 2:
                continue
            ids = {m.id for m in members}
            merged = self.store.add(
                content="Synthesis: " + " | ".join(m.content for m in members), source="sleep:synthesis",
                type="factual", layer="long_term", tags=list(dict.fromkeys(t for m in members for t in m.tags)),
                confidence=max(m.confidence for m in members),
                entities=list(dict.fromkeys(e for m in members for e in m.entities)),
                provenance=Provenance("sleep_synthesis", self.clock(), f"synthesized from {len(members)} memories"),
                derived_from=[m.id for m in members])
            # inherit non-internal relationships
            for rid in dict.fromkeys(r for m in members for r in m.related_to):
                if rid not in ids and rid != merged.id and rid not in merged.related_to \
                        and len(merged.related_to) < DEFAULTS["related_cap"]:
                    merged.related_to.append(rid)
            self.ledger.log(merged.id, "sleep_synthesize", self.actor, details={"sources": group})
            for m in members:
                self.store.delete(m.id, "merged by sleep synthesis")
            self.store.persist(merged)
            synthesized += 1
            log.append(f"synthesized {merged.id} from {', '.join(group)}")
        return SleepReport(backup_id, len(plan.to_consolidate), len(plan.to_archive), synthesized, log)

    def restore(self, backup_id: str) -> None:
        if backup_id not in self.backups:
            raise KeyError(f"H-MEM: unknown backup {backup_id}")
        records, seq = self.backups[backup_id]
        self.store.restore_all(records, seq)
        self.ledger.log("*", "restore", self.actor, details={"backup_id": backup_id})


# ---------------------------------------------------------------- dreaming

class DreamingService:
    """Proposals never become memory until a human calls approve()."""

    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, clock: Callable[[], float], actor: str):
        self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor
        self.proposals: dict[str, DreamProposal] = {}

    @staticmethod
    def _relatedness(a: MemoryRecord, b: MemoryRecord) -> float:
        return (0.5 * max(0.0, cosine(a.embedding, b.embedding)) + 0.2 * jaccard(a.tags, b.tags)
                + 0.1 * (1 if a.domain == b.domain else 0) + 0.2 * jaccard(a.entities, b.entities))

    def _cluster(self) -> list[list[MemoryRecord]]:
        recs = self.store.all()
        used: set[str] = set()
        clusters = []
        for seed in recs:
            if seed.id in used:
                continue
            group = [seed] + [o for o in recs if o.id != seed.id and o.id not in used
                              and self._relatedness(seed, o) >= DEFAULTS["dream_relatedness"]]
            if len(group) >= DEFAULTS["dream_cluster_min_size"]:
                used.update(g.id for g in group)
                clusters.append(group)
        return clusters

    def dream(self) -> list[DreamProposal]:
        cap = DEFAULTS["max_dream_proposals_per_type"]
        created: list[DreamProposal] = []

        def propose(type: str, content: str, derived: list[str], suggested: str | None = None) -> None:
            p = DreamProposal(f"dream-{len(self.proposals) + 1}", type, content, derived, suggested)
            self.proposals[p.id] = p
            created.append(p)
            self.ledger.log(p.id, "dream_proposed", self.actor, details={"type": type, "derived_from": derived})

        for cluster in self._cluster()[:cap]:
            domains = "/".join(dict.fromkeys(m.domain for m in cluster))
            propose("insight", f"Across {len(cluster)} related memories ({domains}): "
                    + " + ".join(m.content for m in cluster), [m.id for m in cluster])

        n = 0
        for m in self.store.all():
            if n >= cap:
                break
            if m.domain != "general":
                continue
            suggested = self.store.classify_domain(m.content, m.tags, m.type)
            if suggested != "general":
                propose("domain", f'Reclassify "{m.content[:60]}" as {suggested}', [m.id], suggested)
                n += 1

        by_domain: dict[str, list[MemoryRecord]] = {}
        for m in self.store.all():
            if m.type in ("preference", "personal") or "event:user_correction" in m.tags:
                by_domain.setdefault(m.domain, []).append(m)
        n = 0
        for domain, items in by_domain.items():
            if n >= cap:
                break
            if len(items) < 2:
                continue
            propose("invariant", f"Stable pattern in {domain}: " + "; ".join(m.content for m in items), [m.id for m in items])
            n += 1
        return created

    def pending(self) -> list[DreamProposal]:
        return [p for p in self.proposals.values() if p.status == "proposed"]

    def _pending(self, proposal_id: str) -> DreamProposal:
        p = self.proposals.get(proposal_id)
        if not p or p.status != "proposed":
            raise KeyError(f"H-MEM: no pending proposal {proposal_id}")
        return p

    def approve(self, proposal_id: str) -> MemoryRecord | None:
        p = self._pending(proposal_id)
        p.status = "approved"
        self.ledger.log(proposal_id, "dream_approved", self.actor, details={"type": p.type})
        if p.type == "domain":
            for mid in p.derived_from:
                if self.store.get(mid) and p.suggested_domain:
                    self.store.update(mid, domain=p.suggested_domain)
            return None
        return self.store.add(
            content=p.content, source="dreaming", type="factual" if p.type == "insight" else "preference",
            layer="long_term", tags=[f"dream:{p.type}"], confidence=0.75,
            provenance=Provenance("dream", self.clock(), f"approved {p.type} proposal"), derived_from=p.derived_from)

    def reject(self, proposal_id: str) -> None:
        p = self._pending(proposal_id)
        p.status = "rejected"  # logged, never materialised
        self.ledger.log(proposal_id, "dream_rejected", self.actor, details={"type": p.type})


# ---------------------------------------------------------------- mining (model-free path)

EVENT_TYPE = {"chat_message": "general", "user_correction": "preference", "file_save": "factual", "file_open": "general",
              "file_edit": "factual", "model_response": "factual", "plan_completion": "factual"}
SIGNAL = re.compile(r"\b(prefer|always|never|decided|chose|choose|use|because|instead|must|should|important|remember)\b", re.I)


def mine_model_free(text: str) -> list[str]:
    """No-model fallback: short direct sentences that carry a memory signal."""
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text)]
    return [s for s in parts if 20 <= len(s) <= 300 and SIGNAL.search(s)][:10]


def parse_strict_json_array(raw: str) -> list[str]:
    """Tolerant parse of a model's JSON array of memory strings (fences and noise stripped)."""
    cleaned = re.sub(r"```\s*$", "", re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.I)).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        return []
    return [x for x in parsed if isinstance(x, str) and len(x.strip()) >= 5] if isinstance(parsed, list) else []


# ---------------------------------------------------------------- facade

class HMEM:
    def __init__(self, db_path: Path | str | None = None, clock: Callable[[], float] | None = None, actor: str = "system"):
        self.clock = clock or (lambda: time.time() * 1000)  # milliseconds, like the reference
        db = _DB(db_path) if db_path is not None else None
        self.ledger = TrustLedgerService(self.clock, db)
        self.store = MemoryStoreService(self.clock, self.ledger, actor, db)
        self.retrieval = MemoryRetrievalService(self.store, self.ledger, self.clock, actor)
        self.conflicts = ConflictDetectionService(self.store, self.ledger, self.clock, actor)
        self.sleep = SleepCycleService(self.store, self.ledger, self.clock, actor)
        self.dreaming = DreamingService(self.store, self.ledger, self.clock, actor)

    def add(self, content: str, source: str, **kw) -> MemoryRecord:
        return self.store.add(content, source, **kw)

    def query(self, query: str, **kw) -> QueryResult:
        return self.retrieval.query(query, **kw)

    def feedback(self, memory_id: str, kind: str) -> None:
        self.retrieval.feedback(memory_id, kind)

    def mine(self, event: str, text: str, chat_id: str | None = None) -> list[MemoryRecord]:
        return [self.store.add(c, f"interaction:{event}", type=EVENT_TYPE[event], layer="short_term",
                               tags=[f"event:{event}"], chat_id=chat_id,
                               provenance=Provenance(event, self.clock(), f"mined from {event}"))
                for c in mine_model_free(text)]
