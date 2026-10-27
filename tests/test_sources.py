from checkam.evidence import SAFE, SCAM, extract, registrable_domain
from checkam.sources import official, patterns, regulators, reports, threats


def test_extract_finds_links_phones_accounts_handles():
    e = extract("Pay to 0123456789 (GTBank), call 0803 123 4567 or +2348031234568, see opay-loans.xyz/claim and @OPay_Support. mail me@x.com")
    assert "opay-loans.xyz/claim" in e.urls and "opay-loans.xyz" in e.domains
    assert e.accounts == ["0123456789"]
    assert e.phones == ["08031234567", "08031234568"]
    assert e.handles == ["opay_support"]
    assert "x.com" not in e.domains  # email addresses are not links


def test_registrable_domain_handles_ng_second_level():
    assert registrable_domain("login.firstbank.com.ng") == "firstbank.com.ng"
    assert registrable_domain("www.opayweb.com") == "opayweb.com"


def test_patterns_catch_advance_fee_and_secrets_once():
    found, topics = patterns.scan("Your loan is approved. Pay a processing fee of N5,000 to unlock it.")
    findings = [f.finding for f in found]
    assert any("pay first" in f for f in findings)
    assert not any("registration, processing" in f for f in findings)  # no duplicate fee note
    assert {"fee", "loan"} <= topics
    found, _ = patterns.scan("Kindly send us the OTP you just received to confirm your account")
    assert found[0].signal == SCAM and found[0].weight == 3


def test_normal_bank_message_has_no_scam_pattern():
    found, _ = patterns.scan("Enter your transaction PIN in the app to confirm the transfer to Mum.")
    assert not any(f.signal == SCAM for f in found)


def test_official_site_is_safe_and_lookalike_is_flagged():
    ev = official.check(extract("Log in at opayweb.com"))
    assert ev[0].signal == SAFE
    ev = official.check(extract("Claim your OPay bonus at opay-bonus.top"))
    assert ev[0].signal == SCAM and "opayweb.com" in ev[0].finding
    ev = official.check(extract("GTBank alert: verify at gtbamk.com"))  # one letter off
    assert ev[0].signal == SCAM


def test_handle_using_brand_name_but_not_official():
    ev = official.check(extract("DM @gtbank_care for your refund"))
    assert ev and "not on our list" in ev[0].finding
    ev = official.check(extract("Follow @gtbank for updates"))
    assert ev[0].signal == SAFE


def test_link_tricks():
    found = threats.tricks("http://opay.secure-verify.top/login")
    text = " ".join(f.finding for f in found)
    assert "puts \"OPay\" in front of a different site" in text and ".top" in text
    assert any("app file" in f.finding for f in threats.tricks("https://loan-fast.ng/download/CashNow.apk"))
    assert any("number address" in f.finding for f in threats.tricks("http://185.22.1.9/bank"))
    assert any("short link" in f.finding for f in threats.tricks("https://bit.ly/3xYz"))
    assert threats.tricks("https://opayweb.com/help") == []


def test_blocklist_match(store):
    store.replace_threats("Phishing Army", [("bad-login.sbs", "")])
    ev = threats.check(extract("verify now https://bad-login.sbs/x"), store)
    assert any(e.source == "Phishing Army" and e.signal == SCAM for e in ev)


def test_sec_warning_names_are_extracted_and_matched(store):
    name, aliases = regulators.subject_aliases("Illegal Operator Alert -CBEX (Crypto Bridge Exchange)-Super Technology-ST Technologies International Ltd April 15, 2025")
    assert "cbex" in aliases and "crypto bridge exchange" in aliases
    assert regulators.subject_aliases("Public Notice On Dividend Warrants Acceptance Into Savings Accounts Aug. 1, 2016") is None
    assert regulators.subject_aliases("Public Notice: Online Retail Foreign Exchange (Forex) Trading Oct. 19, 2017") is None
    store.replace_warned("SEC Nigeria", [(a, name, "Illegal Operator Alert -CBEX", "https://sec.gov.ng/x") for a in aliases])
    ev = regulators.check(extract("Join CBEX, double your money in 30 days"), {"investment"}, store)
    assert any(e.signal == SCAM and "CBEX" in e.finding for e in ev)
    assert any(e.source == "SEC Nigeria" and e.signal != SCAM for e in ev)  # the general SEC rule also attaches


def test_repeat_reports_from_other_people(store):
    e = extract("send to 0123456789")
    for who in ("a", "b", "c"):
        store.record("telegram", who, e.lookups(), "scam")
    ev = reports.check(e, store, "d")
    assert ev and ev[0].signal == SCAM and "3 other people" in ev[0].finding
    assert reports.check(e, store, "a")[0].finding.startswith("2 other people")  # never counts yourself
