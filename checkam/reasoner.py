"""Turns numbered evidence into a verdict. The model must cite evidence for every reason; uncited reasons are dropped.

Order: NVIDIA Nemotron (sponsor model) -> Gemini -> offline rules. Whatever answers, a safety floor applies:
strong scam evidence can never come back as "looks safe".
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from .config import Settings
from .evidence import CAUTION, SAFE, SCAM, Evidence

log = logging.getLogger("checkam.reasoner")

VERDICTS = ("scam", "likely_scam", "not_sure", "looks_safe")

SYSTEM = """You are CheckAm, a scam checker for people in Nigeria: parents, traders, students, first-time phone users.
Someone forwarded you a message, link or account number and asked "is this real?". Independent checks have already run.
Each finding has an id like E3 and a strength from 0 to 4. Strength 4 is decisive (a phishing blocklist hit or a named regulator warning). Decide and explain.

Rules:
- verdict is one of: scam, likely_scam, not_sure, looks_safe.
- Give 2 to 4 reasons. Each reason is one short plain sentence and MUST list the ids of the findings it rests on in "evidence".
- Use only the findings. Never invent facts, dates, numbers, company statements or links.
- Connect findings when they support each other (for example: a new website + a fee to unlock money + a fake brand name).
- "looks_safe" only when findings positively show it is real (for example its link is the company's real website) and nothing points to a scam.
- "not_sure" when there is too little to judge. Then say what to check.
- advice: one or two sentences telling them exactly what to do now (don't pay, don't share codes, call the bank on the number on the back of your card, block and report, etc.).
- Write headline, reasons and advice in the reply language given after the findings: plain English with no jargon, or simple Nigerian Pidgin.

Reply with only this JSON:
{"verdict": "...", "headline": "max 10 words", "reasons": [{"text": "...", "evidence": ["E1"]}], "advice": "..."}"""


@dataclass
class Reason:
    text: str
    evidence: list[str]


@dataclass
class Verdict:
    verdict: str
    headline: str
    reasons: list[Reason]
    advice: str
    reasoner: str  # "nvidia/<model>", "gemini/<model>", "offline"
    notes: list[str] = field(default_factory=list)


def evidence_block(evidence: list[Evidence]) -> str:
    return "\n".join(f"{e.id} [{e.signal}, strength {e.weight}] ({e.source}) {e.finding}" for e in evidence) or "(no findings)"


# Words that mark Nigerian Pidgin. Two or more means the person wrote in Pidgin, so the reply should be in Pidgin too.
PIDGIN = re.compile(r"(?i)\b(abeg|dey|wetin|una|dem|oga|wahala|sef|abi|shey|sabi|pikin|oya|no be|na im|make i|e don|i don|wey|sha)\b")


def language(message: str) -> str:
    return "Nigerian Pidgin" if len(PIDGIN.findall(message)) >= 2 else "English"


def user_prompt(message: str, evidence: list[Evidence]) -> str:
    return (f"Forwarded message:\n\"\"\"\n{message[:3000]}\n\"\"\"\n\nFindings:\n{evidence_block(evidence)}\n\n"
            f"Reply language: {language(message)}")


def score(evidence: list[Evidence]) -> tuple[int, bool, int]:
    bad = sum(e.weight for e in evidence if e.signal in (SCAM, CAUTION))
    strong = any(e.signal == SCAM and e.weight >= 3 for e in evidence)
    good = sum(e.weight for e in evidence if e.signal == SAFE)
    return bad, strong, good


def floor(verdict: str, evidence: list[Evidence]) -> str:
    """Never let strong scam evidence come out as safe or unsure."""
    bad, strong, _ = score(evidence)
    if any(e.signal == SCAM and e.weight >= 4 for e in evidence) and verdict != "scam":
        return "scam" if verdict == "likely_scam" else "likely_scam"
    if strong and verdict in ("looks_safe", "not_sure"):
        return "likely_scam"
    if bad >= 2 and verdict == "looks_safe":
        return "not_sure"
    return verdict


def offline(evidence: list[Evidence]) -> Verdict:
    bad, strong, good = score(evidence)
    strong_count = sum(1 for e in evidence if e.signal == SCAM and e.weight >= 3)
    decisive = any(e.signal == SCAM and e.weight >= 4 for e in evidence)  # blocklist hit or a named regulator warning
    if decisive or strong_count >= 2 or (strong and bad >= 6):
        v = "scam"
    elif strong or bad >= 4:
        v = "likely_scam"
    elif good and bad == 0:
        v = "looks_safe"
    else:
        v = "not_sure"
    ranked = sorted((e for e in evidence if e.signal != "info" or e.weight), key=lambda e: (-e.weight, e.signal != SCAM))
    if v in ("scam", "likely_scam"):
        ranked = [e for e in ranked if e.signal in (SCAM, CAUTION)]
    reasons = [Reason(e.finding, [e.id]) for e in ranked[:4]]
    headline, advice = {
        "scam": ("This is a scam.", "Don't pay, don't click, and don't share any code or PIN. Block the sender."),
        "likely_scam": ("This looks like a scam.", "Don't pay or share any details. If it claims to be your bank, call the number on the back of your card."),
        "not_sure": ("I can't confirm this is real.", "Don't pay or share details until you confirm it through the company's official app, website or office."),
        "looks_safe": ("This looks genuine.", "It still pays to open the company's own app yourself rather than tapping links."),
    }[v]
    if not reasons and v == "not_sure":
        reasons = [Reason("I didn't find a link, account number, company or known scam pattern to check.", [])]
    return Verdict(v, headline, reasons, advice, "offline")


def parse(raw: str, evidence: list[Evidence], reasoner: str) -> Verdict | None:
    raw = re.sub(r"(?is)<think>.*?</think>", "", raw or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    ids = {e.id for e in evidence}
    reasons, dropped = [], 0
    for r in data.get("reasons") or []:
        if not isinstance(r, dict):
            continue
        cited = [i for i in (r.get("evidence") or []) if i in ids]
        text = str(r.get("text", "")).strip()
        if text and cited:
            reasons.append(Reason(text, cited))
        else:
            dropped += 1
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS or not reasons:
        return None
    v = Verdict(floor(verdict, evidence), str(data.get("headline", "")).strip()[:90], reasons[:4],
                str(data.get("advice", "")).strip(), reasoner)
    if v.verdict != verdict:
        v.notes.append(f"safety floor changed {verdict} to {v.verdict}")
        v.headline = offline(evidence).headline
    if dropped:
        v.notes.append(f"dropped {dropped} reason(s) without valid evidence")
    if not v.headline:
        v.headline = offline(evidence).headline
    if not v.advice:
        v.advice = offline(evidence).advice
    return v


# Tried in order when the configured model isn't served to this key (NVIDIA answers 404 per account).
NEMOTRON = ["nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3.5-lightning-30b-a3b"]


async def ask_nvidia(settings: Settings, message: str, evidence: list[Evidence], client: httpx.AsyncClient) -> tuple[str, str]:
    """Returns (reply, model that answered)."""
    models = list(dict.fromkeys([settings.nvidia_model, *NEMOTRON]))
    for model in models:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_prompt(message, evidence)}],
            "temperature": 0.2,
            "max_tokens": 4096,  # Nemotron reasons before answering; the reasoning comes back separately
        }
        r = await client.post(f"{settings.nvidia_base_url}/chat/completions", json=body, timeout=90,
                              headers={"Authorization": f"Bearer {settings.nvidia_api_key}", "Accept": "application/json"})
        if r.status_code == 404 and model != models[-1]:
            log.warning("%s isn't available to this key, trying the next Nemotron model", model)
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"].get("content") or "", model
    raise RuntimeError("no Nemotron model available")


async def ask_gemini(settings: Settings, message: str, evidence: list[Evidence]) -> str:
    import asyncio

    from google import genai
    from google.genai import types

    def call() -> str:
        client = genai.Client(api_key=settings.gemini_api_key)
        resp = client.models.generate_content(
            model=settings.gemini_model, contents=user_prompt(message, evidence),
            config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.2, response_mime_type="application/json"))
        return resp.text or ""

    return await asyncio.to_thread(call)


async def decide(settings: Settings, message: str, evidence: list[Evidence], client: httpx.AsyncClient) -> Verdict:
    order = {"nvidia": ["nvidia", "gemini"], "gemini": ["gemini"], "offline": []}[settings.reasoner]
    for name in order:
        if name == "nvidia" and not settings.nvidia_api_key or name == "gemini" and not settings.gemini_api_key:
            continue
        try:
            if name == "nvidia":
                raw, model = await ask_nvidia(settings, message, evidence, client)
            else:
                raw, model = await ask_gemini(settings, message, evidence), settings.gemini_model
        except Exception as exc:  # network, quota, bad key: fall through to the next reasoner
            log.warning("%s reasoner failed: %s", name, exc)
            continue
        v = parse(raw, evidence, model if name == "nvidia" else f"gemini/{model}")
        if v:
            return v
        log.warning("%s reply had no usable cited verdict", name)
    return offline(evidence)
