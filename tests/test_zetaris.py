import json

import httpx

from checkam import zetaris
from checkam.config import Settings
from checkam.evidence import extract
from checkam.sources import official, regulators

ROWS = {
    "official_accounts": [["Moniepoint", "fintech", "moniepoint", "moniepoint.com", "moniepointinc"]],
    "regulator_warnings": [["ZugaCoin", "zugacoin|zuga coin", "SEC Nigeria", "SEC warned about ZugaCoin.", "https://sec.gov.ng/z"]],
    "regulator_rules": [["sec_rule", "investment", "SEC Nigeria", "Only registered firms may collect investments.", "https://sec.gov.ng/r"]],
    "sec_notices": [["cbex", "CBEX", "Illegal Operator Alert - CBEX", "https://sec.gov.ng/cbex", "SEC Nigeria"]],
}


def fake_zetaris(sent):
    def handle(request):
        body = json.loads(request.content)
        sent.append((body["sql"], request.headers.get("X-Org-ID"), request.headers.get("Authorization")))
        view = next((v for v in ROWS if f"checkam.{v}" in body["sql"]), None)
        return httpx.Response(200, json={"data": ROWS[view] if view else []})
    return handle


def test_setup_file_splits_into_single_statements():
    stmts = zetaris.statements(zetaris.SETUP.read_text(encoding="utf-8"))
    assert len(stmts) == 9  # database, container, 3 REST tables, 4 views
    assert all(";" not in s for s in stmts)
    assert sum("CREATE LIGHTNING REST TABLE" in s for s in stmts) == 3


async def test_sources_read_from_zetaris_when_configured(monkeypatch, store):
    monkeypatch.setattr(official, "_from_data_layer", ())
    monkeypatch.setattr(regulators, "_from_data_layer", {})
    sent = []
    settings = Settings(zetaris_api_key="zk", zetaris_rest_url="http://zetaris.test/api/v1.0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake_zetaris(sent))) as client:
        where = await zetaris.load(settings, client)
    assert where.startswith("Zetaris (1 official accounts")
    assert all(org == "1" and auth == "Bearer zk" for _, org, auth in sent)
    assert official.owner_of("moniepoint.com").name == "Moniepoint"
    assert official.lookalike("moniepoint-loans.xyz").name == "Moniepoint"
    found = regulators.check(extract("Invest in CBEX and ZugaCoin now"), {"investment"}, store)
    assert {e.url for e in found} == {"https://sec.gov.ng/z", "https://sec.gov.ng/cbex", "https://sec.gov.ng/r"}


async def test_sample_mode_without_zetaris(monkeypatch):
    monkeypatch.setattr(official, "_from_data_layer", ())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        assert (await zetaris.load(Settings(), client)).startswith("local files (sample mode")
        down = await zetaris.load(Settings(zetaris_api_key="zk"), client)
    assert down.startswith("local files (Zetaris unavailable")
    assert official.owner_of("opayweb.com").name == "OPay"  # bundled list still works
