"""Known Nigerian scam patterns in the message text itself. Offline and instant."""

from __future__ import annotations

import re

from ..evidence import CAUTION, SCAM, Evidence

SOURCE = "Message check"

# (pattern, signal, weight, plain finding, topic). Topics let regulator rules attach to the right message.
PATTERNS: list[tuple[re.Pattern, str, int, str, str]] = [
    (re.compile(r"\b(pay|send|deposit|transfer)\b.{0,40}\b(fee|charge|amount|deposit|₦|n\d|naira)\b.{0,60}\b(unlock|release|receive|withdraw|claim|activate|access|process|disburse)", re.I | re.S),
     SCAM, 3, "It asks you to pay first before you can receive money. That is the classic advance-fee scam.", "fee"),
    (re.compile(r"\b(unlock|release|receive|withdraw|claim|activate|disburse)\b.{0,60}\b(fee|pay|payment|charge)\b", re.I | re.S),
     SCAM, 3, "It asks you to pay first before you can receive money. That is the classic advance-fee scam.", "fee"),
    (re.compile(r"\b(recruitment|employment|job|vacanc(y|ies)|scholarship|grant|empowerment|palliative|n-power|npower|visa|lottery)\b.{0,80}\b(fee|pay|payment|charge)\b"
                r"|\b(fee|pay|payment|charge)\b.{0,80}\b(recruitment|employment|job|vacanc(y|ies)|scholarship|grant|empowerment|palliative|n-power|npower)\b", re.I | re.S),
     SCAM, 3, "It asks you to pay to get a job, grant, scholarship or government support. Real recruitment and grants never charge you to apply.", "fee"),
    (re.compile(r"\b(share|send|tell|give|enter|confirm|provide|forward)\b.{0,25}\b(otp|one[- ]time (password|pin|code)|atm pin|card pin|your pin|pin number|cvv|bvn|password|token code)\b", re.I | re.S),
     SCAM, 3, "It asks for your PIN, OTP, BVN, password or card details. Real banks and companies never ask for these in a message.", "secret"),
    (re.compile(r"\b(double your (money|investment)|guaranteed (returns?|profit|income)|\d{1,3}\s?% (daily|weekly|per day|per week|monthly returns?)|risk[- ]free (investment|returns?)|returns? of \d{2,3}\s?%)", re.I),
     SCAM, 3, "It promises guaranteed or very high returns. Real investments can't promise that; Ponzi schemes do.", "investment"),
    (re.compile(r"\b(invest(ment)?|trading platform|forex|crypto|bitcoin|usdt|mining|cooperative|contribution scheme|ajo)\b", re.I),
     CAUTION, 1, "It's about an investment or money scheme, where most large scams in Nigeria happen.", "investment"),
    (re.compile(r"\b(loan|borrow|credit limit|quick cash|soft loan)\b", re.I),
     CAUTION, 1, "It's about a loan. Fake loan apps often ask for a 'processing fee' and then vanish.", "loan"),
    (re.compile(r"\b(congratulations|you (have )?won|lucky winner|selected (as|for) (a )?winner|promo winner|giveaway|cash prize)\b", re.I),
     CAUTION, 2, "It says you've won a prize or promo. If you never entered, that's a common hook.", "prize"),
    (re.compile(r"\b(urgent(ly)?|immediately|within (24|48) ?hours|act now|last chance|today only|expires? (today|soon))\b", re.I),
     CAUTION, 1, "It pushes you to act fast. Pressure is a scammer's tool; real companies give you time.", "pressure"),
    (re.compile(r"\b(account|card|sim|line|bvn|nin|wallet)\b.{0,20}\b(will be|has been|is)\b.{0,10}\b(blocked|suspended|deactivated|closed|restricted|frozen|barred)\b", re.I | re.S),
     CAUTION, 2, "It threatens that your account or line will be blocked. That threat is used to rush people into sharing details.", "threat"),
    (re.compile(r"\b(registration|application|training|processing|clearance|activation|delivery|customs)\s+(fee|charge)\b", re.I),
     CAUTION, 2, "It mentions a registration, processing or clearance fee. Fake jobs, loans and deliveries use these to collect money.", "fee"),
    (re.compile(r"\b(you have been credited|credit alert|credited (with|to your account)).{0,120}\b(mistake|error|wrongly|refund|reverse|send (it )?back)\b", re.I | re.S),
     SCAM, 3, "It claims money was sent to you by mistake and asks you to send it back. That's a fake-alert scam: check your real balance in your bank app.", "fee"),
    (re.compile(r"\b(whatsapp|call|chat with)\b.{0,30}\b(customer care|support|agent|account officer|helpdesk)\b|\b(customer care|support|account officer)\b.{0,30}\bwhatsapp\b", re.I | re.S),
     CAUTION, 1, "It sends you to a 'support agent' on WhatsApp or a phone line. Scammers pose as customer care this way.", "impersonation"),
    (re.compile(r"\b(work from home|earn (₦|n)?\d[\d,]* (daily|weekly|per day)|like and earn|task(s)? and earn|online job)\b", re.I),
     CAUTION, 2, "It's an 'earn money online' job. Many of these ask you to pay or deposit first.", "job"),
]


def scan(text: str) -> tuple[list[Evidence], set[str]]:
    """Findings from the text, plus the topics it touches (fee, loan, investment, ...)."""
    found: list[Evidence] = []
    topics: set[str] = set()
    seen: set[str] = set()
    for pattern, signal, weight, finding, topic in PATTERNS:
        if pattern.search(text):
            # the generic "fee" note adds nothing once the stronger pay-first finding is in
            if topic == "fee" and signal == CAUTION and "fee" in topics:
                continue
            topics.add(topic)
            if finding not in seen:
                seen.add(finding)
                found.append(Evidence(SOURCE, finding, signal, weight))
    return found, topics
