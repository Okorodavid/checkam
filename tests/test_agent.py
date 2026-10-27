import json

from checkam.evidence import CAUTION, SAFE, SCAM, Evidence
from checkam.reasoner import floor, offline, parse
from checkam.render import chat_text

MUM = ("Congratulations! Your OPay loan of N150,000 is approved. Pay a processing fee of N5,000 to 8123456789 "
       "to unlock and receive your money within 24 hours. Visit opay-loans.xyz/claim")


def ev(*items):
    out = [Evidence("s", f, sig, w) for f, sig, w in items]
    for i, e in enumerate(out, 1):
        e.id = f"E{i}"
    return out


async def test_mums_message_is_a_scam_with_cited_reasons(checker):
    report = await checker.check(MUM, "test", "mum")
    v = report.verdict
    assert v.verdict == "scam"
    ids = {e.id for e in report.evidence}
    assert all(r.evidence and set(r.evidence) <= ids for r in v.reasons)
    findings = " ".join(e.finding for e in report.evidence)
    assert "created 5 days ago" in findings  # RDAP domain age
    assert "not their website" in findings  # fake OPay link
    text = chat_text(report)
    assert text.startswith("🔴") and "Why:" in text and "Sources:" in text


async def test_real_company_link_alone_looks_safe(checker):
    report = await checker.check("Download the app from opayweb.com", "test", "u")
    assert report.verdict.verdict == "looks_safe"


async def test_nothing_to_check_is_not_sure(checker):
    report = await checker.check("Hello, are you coming to the meeting tomorrow?", "test", "u")
    assert report.verdict.verdict == "not_sure"


def test_model_reasons_without_valid_evidence_are_dropped():
    evidence = ev(("pay first", SCAM, 3), ("new site", SCAM, 3))
    raw = json.dumps({"verdict": "scam", "headline": "Scam", "advice": "Don't pay.",
                      "reasons": [{"text": "Fee first.", "evidence": ["E1"]}, {"text": "Made up.", "evidence": ["E9"]},
                                  {"text": "No cite.", "evidence": []}]})
    v = parse("<think>hmm</think>" + raw, evidence, "nvidia/x")
    assert [r.text for r in v.reasons] == ["Fee first."]
    assert any("dropped 2" in n for n in v.notes)


def test_safety_floor_overrides_a_model_that_says_safe():
    evidence = ev(("pay first", SCAM, 3))
    raw = json.dumps({"verdict": "looks_safe", "headline": "Fine", "advice": "ok", "reasons": [{"text": "x", "evidence": ["E1"]}]})
    v = parse(raw, evidence, "nvidia/x")
    assert v.verdict == "likely_scam" and v.notes
    assert floor("looks_safe", ev(("a", CAUTION, 2))) == "not_sure"


def test_unusable_model_reply_returns_none():
    assert parse("Sorry, I can't help.", ev(("x", SCAM, 3)), "nvidia/x") is None
    assert parse(json.dumps({"verdict": "maybe", "reasons": []}), ev(("x", SCAM, 3)), "nvidia/x") is None


def test_offline_rules():
    assert offline(ev(("a", SCAM, 3), ("b", SCAM, 3))).verdict == "scam"
    assert offline(ev(("a", SCAM, 3))).verdict == "likely_scam"
    assert offline(ev(("a", SAFE, 1))).verdict == "looks_safe"
    assert offline(ev(("a", CAUTION, 1))).verdict == "not_sure"
