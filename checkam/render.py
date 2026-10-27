"""How a verdict looks in a chat. Plain text works everywhere (Telegram, Discord, WhatsApp)."""

from __future__ import annotations

from .agent import Report

BADGE = {"scam": "🔴", "likely_scam": "🟠", "not_sure": "🟡", "looks_safe": "🟢"}
WHY = {"en": "Why", "pcm": "Why"}


def chat_text(report: Report, max_len: int = 3500) -> str:
    v = report.verdict
    by_id = {e.id: e for e in report.evidence}
    # number sources in the order reasons cite them
    cited: list[str] = []
    for r in v.reasons:
        for i in r.evidence:
            if i in by_id and i not in cited:
                cited.append(i)
    num = {eid: n for n, eid in enumerate(cited, 1)}

    lines = [f"{BADGE.get(v.verdict, '🟡')} {v.headline}", "", "Why:"]
    for k, r in enumerate(v.reasons, 1):
        refs = "".join(f"[{num[i]}]" for i in r.evidence if i in num)
        lines.append(f"{k}. {r.text} {refs}".rstrip())
    lines += ["", v.advice]
    sources = [(num[i], by_id[i]) for i in cited]
    if sources:
        lines += ["", "Sources:"]
        for n, e in sources:
            lines.append(f"[{n}] {e.source}" + (f": {e.url}" if e.url else ""))
    text = "\n".join(lines)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def detail_text(report: Report) -> str:
    """Everything the agent found, for the CLI and for judges."""
    v = report.verdict
    lines = [chat_text(report), "", f"--- all findings ({len(report.evidence)}) via {v.reasoner} in {report.seconds:.1f}s ---"]
    for e in report.evidence:
        lines.append(f"{e.id} [{e.signal}/{e.weight}] {e.source}: {e.finding}" + (f" <{e.url}>" if e.url else ""))
    for n in v.notes:
        lines.append(f"note: {n}")
    return "\n".join(lines)
