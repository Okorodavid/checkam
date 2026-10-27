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


def test_reply_language_follows_the_message():
    from checkam.reasoner import language
    assert language(MUM) == "English"
    assert language("Abeg check am: dem say make I pay 3k registration fee for NNPC recruitment") == "Nigerian Pidgin"


def test_findings_from_the_same_source_share_one_number():
    from checkam.agent import Report
    from checkam.evidence import Entities
    from checkam.reasoner import Reason, Verdict
    evidence = ev(("fee first", SCAM, 3), ("act fast", CAUTION, 1))
    verdict = Verdict("scam", "This is a scam.", [Reason("Fee and pressure.", ["E1", "E2"])], "Don't pay.", "offline")
    text = chat_text(Report(MUM, Entities(text=MUM), evidence, verdict, 0.1))
    assert "Fee and pressure. [1]" in text
    assert text.count("[1] s") == 1 and "[2]" not in text


async def test_nemotron_falls_back_when_a_model_is_not_served():
    import httpx
    from checkam.config import Settings
    from checkam.reasoner import NEMOTRON, ask_nvidia
    asked = []

    def nvidia(request):
        model = json.loads(request.content)["model"]
        asked.append(model)
        if model == NEMOTRON[0]:
            return httpx.Response(404, json={"detail": "Not found for account"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(nvidia)) as client:
        _, model = await ask_nvidia(Settings(nvidia_api_key="k"), [], client)
    assert asked[:2] == NEMOTRON[:2] and model == NEMOTRON[1]


async def test_nightshift_is_the_primary_provider_and_picks_a_nemotron_route():
    import httpx
    from checkam.config import Settings
    from checkam.reasoner import decide
    seen = []
    good = json.dumps({"verdict": "scam", "headline": "Scam", "advice": "Don't pay.",
                       "reasons": [{"text": "Fee first.", "evidence": ["E1"]}]})

    def nightshift(request):
        seen.append((request.method, request.url.path, request.headers.get("meterless-app")))
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "meterless/auto"}, {"id": "meterless/nemotron-fast"}]})
        assert json.loads(request.content)["model"] == "meterless/nemotron-fast"
        return httpx.Response(200, json={"model": "nvidia/nemotron-3.5-lightning-30b-a3b",
                                         "choices": [{"message": {"content": good}}]})

    settings = Settings(meterless_runtime_token="token", meterless_base_url="http://nightshift.test/v1", nvidia_api_key="k")
    async with httpx.AsyncClient(transport=httpx.MockTransport(nightshift)) as client:
        v = await decide(settings, MUM, ev(("fee first", SCAM, 3)), client)
    assert v.reasoner == "meterless:nvidia/nemotron-3.5-lightning-30b-a3b"
    assert all(app == "checkam" for _, _, app in seen)
    assert "evaluator: accepted" in v.trace[0]


async def test_evaluator_sends_a_bad_draft_back_for_one_revision():
    import httpx
    from checkam.config import Settings
    from checkam.reasoner import decide
    drafts = [
        {"verdict": "scam", "headline": "Scam", "advice": "Don't pay.",
         "reasons": [{"text": "Fee first.", "evidence": ["E1"]}, {"text": "Made up.", "evidence": ["E9"]}]},
        {"verdict": "scam", "headline": "Scam", "advice": "Don't pay.", "reasons": [{"text": "Fee first.", "evidence": ["E1"]}]},
    ]
    asked = []

    def nvidia(request):
        asked.append(json.loads(request.content)["messages"][-1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(drafts[len(asked) - 1])}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(nvidia)) as client:
        v = await decide(Settings(nvidia_api_key="k"), MUM, ev(("fee first", SCAM, 3)), client)
    assert len(asked) == 2 and "previous reply had problems" in asked[1]
    assert v.notes == [] and len(v.trace) == 2 and v.trace[1].endswith("evaluator: accepted")
