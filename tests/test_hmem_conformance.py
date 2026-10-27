"""The H-MEM conformance suite (engines/hmem/conformance/runner.ts) ported to pytest.

Every check in runner.ts is ported, one test case per vector in tests/data/hmem_vectors.json:
record-validation, feedback-deltas, ranking-order, sleep-guardrails, conflict-gate,
ledger-audit and dream-boundary (13 checks). None are left out. Extra tests at the end cover
behaviour the runner does not check: persistence across instances, sleep restore, and mining.
"""

import json
from pathlib import Path

import pytest

from checkam.hmem import DAY_MS, HMEM, mine_model_free, parse_strict_json_array

VECTORS = json.loads((Path(__file__).parent / "data" / "hmem_vectors.json").read_text(encoding="utf-8"))
T0 = VECTORS["clock"]


def cases(section):
    return pytest.mark.parametrize("c", VECTORS["sections"][section], ids=lambda c: c["id"])


def approx(a, b, eps=1e-9):
    return a is not None and abs(a - b) < eps


@cases("record-validation")
def test_record_validation(c):
    hmem = HMEM(clock=lambda: T0)
    try:
        hmem.add(c["input"]["content"], c["input"]["source"])
        rejected = False
    except ValueError:
        rejected = True
    assert rejected == (c["expect"] == "reject")


@cases("feedback-deltas")
def test_feedback_deltas(c):
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add("feedback target record", "conformance", confidence=c["start"])
    before = m.access_count
    hmem.feedback(m.id, c["kind"])
    after = hmem.store.get(m.id)
    assert approx(after.confidence, c["expectConfidence"])
    if "expectAccessDelta" in c:
        assert after.access_count - before == c["expectAccessDelta"]
    if "expectTag" in c:
        assert c["expectTag"] in after.tags


@cases("ranking-order")
def test_ranking_order(c):
    hmem = HMEM(clock=lambda: T0)
    by_key = {r["key"]: hmem.add(r["content"], "conformance", confidence=r["confidence"], layer=r["layer"])
              for r in c["records"]}
    for r in c["records"]:
        if r.get("supersededByKey"):
            by_key[r["key"]].superseded_by = by_key[r["supersededByKey"]].id
    order = [m.memory.id for m in hmem.query(c["query"], threshold=0, top_n=10).memories]
    expected = [by_key[k].id for k in c["expectOrder"]]
    for first, second in zip(expected, expected[1:]):
        assert order.index(first) < order.index(second), order


@cases("sleep-guardrails")
def test_sleep_guardrails(c):
    now = [T0]
    hmem = HMEM(clock=lambda: now[0])
    by_key = {r["key"]: hmem.add(r["content"], r["source"], derived_from=r.get("derivedFrom")) for r in c["records"]}
    now[0] = T0 + c["ageDays"] * DAY_MS
    before = sorted(m.id for m in hmem.store.all())
    preview = hmem.sleep.preview()
    assert sorted(m.id for m in hmem.store.all()) == before, "preview mutated the store"
    for k in c["expectArchived"]:
        assert by_key[k].id in preview.to_archive
    for k in c["expectProtected"]:
        assert by_key[k].id not in preview.to_archive
    report = hmem.sleep.execute(preview)
    for k in c["expectProtected"]:
        assert hmem.store.get(by_key[k].id) is not None
    assert report.backup_id


@cases("conflict-gate")
def test_conflict_gate(c):
    hmem = HMEM(clock=lambda: T0)
    a = hmem.add(c["a"]["content"], "conformance", confidence=c["a"]["confidence"])
    b = hmem.add(c["b"]["content"], "conformance", confidence=c["b"]["confidence"])
    found = hmem.conflicts.scan()
    assert found, "opposing always/never pair on similar content must be detected"
    outcome = hmem.conflicts.auto_resolve(found[0])
    assert outcome in ("resolved", "queued")
    if outcome == "resolved":
        assert any(m.superseded_by for m in (hmem.store.get(a.id), hmem.store.get(b.id)))
    assert hmem.store.get(a.id) and hmem.store.get(b.id), "conflict resolution must never delete records"


@cases("ledger-audit")
def test_ledger_audit(c):
    hmem = HMEM(clock=lambda: T0)
    m = hmem.add("audited record", "conformance", confidence=c["start"])
    hmem.feedback(m.id, c["kind"])
    history = hmem.ledger.history(m.id)
    assert [h.action for h in history] == c["expectActions"]
    assert approx(history[-1].previous_state["confidence"], c["expectPrev"])
    assert approx(history[-1].new_state["confidence"], c["expectNew"])


@cases("dream-boundary")
def test_dream_boundary(c):
    hmem = HMEM(clock=lambda: T0)
    for r in c["records"]:
        hmem.add(r["content"], "conformance", type=r["type"])
    count = len(hmem.store.all())
    proposals = hmem.dreaming.dream()
    assert proposals, "two related preferences must produce at least one proposal"
    assert len(hmem.store.all()) == count, "dreaming must not materialise anything before approval"
    created = hmem.dreaming.approve(proposals[0].id)
    if created:
        assert created.layer == "long_term" and created.derived_from


# ---------------------------------------------------------------- beyond the runner

def test_durable_tiers_survive_a_new_instance_and_short_term_does_not(tmp_path):
    db = tmp_path / "h.db"
    first = HMEM(db, clock=lambda: T0)
    kept = first.add("the deploy window is monday morning", "test", layer="long_term")
    first.add("scratch note for this session only", "test", layer="short_term")
    first.feedback(kept.id, "helpful")
    second = HMEM(db, clock=lambda: T0)
    assert [m.content for m in second.store.all()] == [kept.content]
    assert approx(second.store.get(kept.id).confidence, 0.75)
    assert [h.action for h in second.ledger.history(kept.id)] == ["create", "feedback"]
    assert second.add("another", "test").id == "mem-3"  # ids never collide across instances


def test_sleep_restore_brings_archived_memories_back():
    now = [T0]
    hmem = HMEM(clock=lambda: now[0])
    m = hmem.add("random one-off note about parking near the office", "chat")
    now[0] = T0 + 40 * DAY_MS
    report = hmem.sleep.execute()
    assert hmem.store.get(m.id) is None and report.archived == 1
    hmem.sleep.restore(report.backup_id)
    assert hmem.store.get(m.id) is not None
    assert "restore" in hmem.ledger.stats()


def test_model_free_mining_and_tolerant_parsing():
    assert mine_model_free("Hi. I always use dark mode because it is easier on my eyes.") == [
        "I always use dark mode because it is easier on my eyes."]
    assert parse_strict_json_array('```json\n["prefer short answers", 3, "no"]\n```') == ["prefer short answers"]
    assert parse_strict_json_array("not json") == []
